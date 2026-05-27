import glob
import hashlib
import logging
import re
from abc import ABC, abstractmethod
from os import PathLike
from pathlib import Path
from typing import List, NamedTuple, Tuple, Optional, Union, Generator

import git

from cofee.change_types import ChangeTypes

logger = logging.getLogger(__name__)

EMPTY_HASH = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

class Entry(NamedTuple):
    """A single entry in the dataset."""
    key: Union[str, None]
    commit_hash: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    committed_date: int
    authored_date: int
    file_path: Optional[str]
    previous_file_path: Optional[str]
    file_hash: Optional[str]
    file_mode: Optional[str]
    previous_file_hash: Optional[str]
    previous_file_mode: Optional[str]
    git_change_type: ChangeTypes
    commit_number: int

class SummaryDiff(NamedTuple):
    commit_hash: str
    file_path: Optional[str]


class Extractor(ABC):
    """An extractor is used to extract information from a repository."""

    def __init__(self, repository: git.Repo) -> None:
        self.repository = repository

    def extract_all(self, *args, **kwargs) -> List[Entry]:
        return list(self.extract(*args, **kwargs))

    @abstractmethod
    def extract(self, from_ref="HEAD", after=None, *args, **kwargs) -> List[Entry]:
        """Extract the information from the repository. Note this function act as a generator, and will be lazy evaluated.

        Returns:
        List[Entry]: The list of entries extracted from the repository.
        """
        pass

class FilesExtractor(Extractor):

    def __init__(self, repository: git.Repo, filters: dict[str, List[str]], save_directory: Path, case_sensitive=False):
        super().__init__(repository)
        self.save_directory = Path(save_directory)
        if not self.save_directory.is_dir():
            self.save_directory.mkdir(exist_ok=True)
        self.filters = filters
        self.case_sensitive = case_sensitive
        self.regexes: list[tuple[int, str, list[re.Pattern]]] = []
        for k, v in self.filters.items():
            p = k.split("-")[-1]
            if p.isdigit():
                priority = int(p)
                k = "-".join(k.split("-")[:-1]) # removes priority from results
            else:
                priority = 0
            vs = [vi + "**" if vi.endswith("/") else vi for vi in v]
            if not case_sensitive:
                vs += [vi.lower() for vi in vs]
                vs = set(vs)
            self.regexes.append((priority, k, [re.compile(glob.translate(vi, recursive=True, include_hidden=True)) for vi in vs]))
        self.regexes.sort(key=(lambda k: k[0]), reverse=True)


    def _path_corresponds_to(self, path: str):
        if path is None:
            return None
        if not self.case_sensitive:
            path = path.lower() if path is not None else None
        for _, k, p in self.regexes:
            for pattern in p:
                if path is not None and pattern.match(path):
                    return k
        return None

    def _diff_corresponds_to(self, diff: git.Diff):
        return (self._path_corresponds_to(diff.a_path), self._path_corresponds_to(diff.b_path))

    def _parse_git_log_stream(self, from_ref: str, after=None) -> Generator[SummaryDiff]:
        _SEPARATOR = "COMMIT:"
        if after is not None:
            from_ref = f"{after}..{from_ref}"
        t = self.repository.git.log(
            from_ref,
            **{
                "first-parent": True,
                "name-only": True,
                "no-renames": True,
                "pretty": f"format:{_SEPARATOR}%H",
            },
        )
        for commit in t.split(_SEPARATOR):
            parts = commit.split('\n')
            for f in parts[1:]:
                fs = f.strip()
                fs = fs.strip('"') # on unknown characters, git might put quotes around it.
                if self._path_corresponds_to(fs) is not None:
                    yield parts[0].strip()
                    break

    def extract(self, from_ref="HEAD", after=None, *args, **kwargs) -> Generator[Entry]:
        for i, commit_hash in enumerate(
            self._parse_git_log_stream(from_ref, after)
        ):
            e = self._extract_files(i, commit_hash)
            yield from e

    def _extract_files(self, commit_number: int, commit_hash) -> Union[List[Entry], None]:
        commit = self.repository.commit(commit_hash)
        parent = commit.parents[0] if len(commit.parents) > 0 else None
        diffs = parent.diff(commit) if parent else commit.diff(git.NULL_TREE)
        res = []
        for diff in diffs:
            akey, bkey = self._diff_corresponds_to(diff)
            if akey is None and bkey is None:
                continue  # a commit might contains diffs for files we do not care about
            try:
                res.append(self._process_diff(akey, bkey, diff, commit, commit_number))
            except ValueError:
                logger.error(
                    "Could not process diff %s (commit=%s)",
                    str(diff),
                    commit,
                    exc_info=True,
                )
                raise
        return res

    def _process_diff(
            self,
            akey: str,
            bkey: str,
            diff: git.Diff,
            commit: git.Commit,
            commit_number: int
    ) -> Union[Entry, None]:
        """Process a diff to extract the files and data.

        Args:
        diff (git.Diff): The diff to process.
        entries (List[Entry]): The list of entries representing the dataset.
        commit (git.Commit): The commit to which the diff belongs.
        parent (git.Commit, optional): The parent of the commit (if None, will try
        to get it automatically). Defaults to None.
        """
        try:
            change_type = ChangeTypes(diff.change_type)
        except ValueError:
            logger.error(
                "Could not process diff %s (commit=%s, change_type=%s)",
                str(diff),
                commit,
                diff.change_type,
            )
            return  # we do not care about this diff

        params = self._get_blob_parameters(diff, change_type, commit)
        return self._save_entry(*self._process_blob(*params, akey=akey, bkey=bkey, commit_number=commit_number))

    def _get_blob_content(self, blob: git.Blob) -> Tuple[Optional[str], Optional[str]]:
        """
        Save the content of a git blob to a file.

        Args:
        blob (git.Blob): The git blob object.

        Returns:
        str: The name under which the file was saved.
        """
        if blob is None:
            return None, None
        data = blob.data_stream.read()
        _hash = hashlib.sha256(data).hexdigest()
        return data, _hash

    def _save_content(self, data: bytes, old_data: bytes, entry: Entry) -> Optional[str]:
        """
        Save the content of a git blob to a file.

        Args:
        data (bytes): The data to save.
        path (PathLike): The directory where the file will be saved.

        Returns:
        str: The name under which the file was saved.
        """
        if self.save_directory is None:
            return
        for (d, h) in [(data, entry.file_hash), (old_data, entry.previous_file_hash)]:
            if d is None or h is None:
                continue
            path = self.save_directory / h
            if not path.exists():
                # if it exists, we already have the workflow
                # (well, we might have a collision, but it is unlikely)
                with open(path, "wb") as file:
                    file.write(d)

    def _get_blob_parameters(
            self, diff: git.Diff, change_type: ChangeTypes, commit
    ) -> tuple:
        """Returns the parameters to process a blob.

        Args:
        diff (git.Diff): The diff to process.
        change_type (ChangeTypes): The type of change.
        commit (_type_): The commit to which the diff belongs.

        Returns:
        List[tuple]: The parameters to process a blob.
        """
        # separated as both path is not None in case of deletion and addition
        if change_type == ChangeTypes.DELETED:
            blob, mode, old_blob, old_mode, path, previous_path = None, None, diff.a_blob, oct(diff.a_mode), None, diff.a_path
        elif change_type == ChangeTypes.ADDED:
            blob, mode, old_blob, old_mode, path, previous_path = diff.b_blob, oct(diff.b_mode), None, None, diff.b_path, None
        else:
            blob, mode, old_blob, old_mode, path, previous_path = (
                diff.b_blob,
                oct(diff.b_mode),
                diff.a_blob,
                oct(diff.a_mode),
                diff.b_path,
                diff.a_path,
            )
        return (blob, mode, old_blob, old_mode, commit, path, previous_path, change_type)

    def _save_entry(self, entry: Entry, data: bytes, old_data: bytes):
        self._save_content(data, old_data, entry)
        return entry

    def _process_blob(
            self,
            blob: git.Blob,
            mode,
            old_blob: git.Blob,
            old_mode,
            commit: git.Commit,
            workflow_path: PathLike,
            previous_workflow_path: PathLike,
            change_type: ChangeTypes,
            commit_number: int,
            akey: str,
            bkey: str
    ) -> tuple[Entry, Optional[str], Optional[str]]:
        """Process a blob to extract the workflow content.

        Args:
        blob (git.Blob): The blob to process.

        Returns:
        str: The hash of the workflow content. (Its name in the save_directory)
        """
        if mode != "0o160000": # excludes submodules
            data, _hash = self._get_blob_content(blob)
        else:
            data, _hash = None, None
        if old_mode != "0o160000": # excludes submodules
            old_data, _old_hash = self._get_blob_content(old_blob)
        else:
            old_data, _old_hash = None, None
        # if change_type == ChangeTypes.RENAMED and _hash != _old_hash:
        #     change_type = ChangeTypes.MODIFIED
        entry = Entry(
            bkey or akey,
            commit.hexsha,
            commit.author.name,
            commit.author.email,
            commit.committer.name,
            commit.committer.email,
            commit.committed_date,
            commit.authored_date,
            workflow_path,
            previous_workflow_path,
            _hash if bkey is not None else None,
            mode,
            _old_hash if akey is not None else None,
            old_mode,
            change_type.value,
            commit_number
        )
        return entry, data, old_data
