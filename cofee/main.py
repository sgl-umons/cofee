import logging
import os
import shutil
import sys
import tempfile
import time
import tomllib
from pathlib import Path

import click
import git
from git import GitCommandError

from cofee.extractors import FilesExtractor
from cofee.params_type import GitReference
from cofee.repository import clone_repository, read_repository, update_repository
from cofee.utils import write_csv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# See https://click.palletsprojects.com/en/8.1.x/documentation/#help-texts
CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"]}

def open_repository(path: str, save_at: Path = None, update: bool = False):
    try:
        if os.path.isdir(path):
            repo = read_repository(path)
        elif save_at is not None and os.path.isdir(os.path.join(save_at, ".git")):
            repo = read_repository(save_at)
        else:
            repo = clone_repository(path, save_at)
    except (git.exc.GitCommandError, ValueError) as exception:
        logger.error("Could not read repository at '%s'", path)
        logger.debug(exception)
        return None
    if update:
        try:
            update_repository(repo)
        except GitCommandError as e:
            logger.error(
                "Could not update repository at '%s'. Keeping the current version...",
                path
            )
            logger.debug(e)
    return repo

@click.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--ref",
    "--branch",
    "-r",
    default="HEAD",
    help="The most recent commit reference (i.e., commit SHA or TAG) to be considered for the extraction.",
    type=GitReference(),
)
@click.option(
    "--save-repository",
    "-s",
    help="Save the repository to the given directory in case `REPOSITORY` was distant.",
    type=click.Path(exists=False, file_okay=False, dir_okay=True, writable=True),
)
@click.option(
    "--delete-if-no-entries",
    help="In case --save-repository/-s was given or if the repository is local, delete the repository if no entries were generated from this repository.",
    is_flag=True
)
@click.option(
    "--update", "-u", help="Fetch the repository at the given path.", is_flag=True
)
@click.option(
    "--after",
    "-a",
    help="Only consider commits after the given commit reference (i.e., commit SHA or TAG).",
    type=GitReference(),
)
@click.option(
    "--files",
    "-f",
    help="The directory where the extracted files will be stored.",
    default="files",
    type=click.Path(exists=False, file_okay=False, dir_okay=True, writable=True),
)
@click.option(
    "--output",
    "-o",
    help="The output CSV file where information related to the dataset will be stored. "
    "By default, the information will written to the standard output.",
    type=click.Path(exists=False, file_okay=True, dir_okay=False, writable=True),
)
@click.option(
    "--repository-name",
    "-n",
    help="Add a column `repository` to the output file where each value will be equal to the provided parameter.",
    type=str,
)
@click.option(
    "--no-headers",
    help="Remove the header row from the CSV output file.",
    is_flag=True,
)
@click.option(
    "--config",
    '-c',
    help="Configuration files for the different filters",
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True)
)
@click.argument(
    "repository",
    type=str,
)
def main(
        ref,
        save_repository,
        delete_if_no_entries,
        update,
        after,
        files,
        output,
        repository_name,
        no_headers,
        config,
        repository
):
    """Extract the files from a single Git repository `REPOSITORY`.
    The extraction is done by traversing the Git history of the repository starting
    from the reference given to `-r` and going back in time respecting the first-parent rule until
    the first commit (or the reference given to `-a`) is reached.
    The Git repository can be local or distant. In the latter case, it will be pulled
    locally and deleted unless specified otherwise.
    Every extracted file will be stored in the directory given to `-f` (or the
    directory `files` if not specified).
    The metadata related to the extracted files will be written in the CSV file given to `-o`,
    or in the standard output if not specified.

    Example of usage:
    cofee https://github.com/sgl-umons/cofee -c config.toml
    """
    repo = None
    tmp_directory = None
    tries = 0
    while repo is None and tries < 3:
        if tries > 0:
            logger.warning("Failed pulling repository '%s'... Waiting 10 seconds and retying...", repository)
            time.sleep(10)
        tries += 1
        if tmp_directory:
            tmp_directory.cleanup()
        if save_repository is None and not os.path.exists(repository):
            tmp_directory = tempfile.TemporaryDirectory(dir=".")
            save_repository = tmp_directory.name
        repo = open_repository(repository, save_repository, update)
    if repo is None:
        logger.error("Failed pulling repository '%s' after 3 tries!", repository)
        exit(1)

    case_sensitive = False
    filters = {"*": ["*"]}
    if config is not None:
        with open(config) as f:
            config_d = tomllib.loads(f.read())
            case_sensitive = config_d.get("general", {"case-sensitive": case_sensitive}).get("case-sensitive", False)
            filters = config_d.get("filters", filters)

    logger.info("Beginning extraction of '%s'", repository)
    extractor = FilesExtractor(repo, filters, files, case_sensitive=case_sensitive)
    entries = extractor.extract_all(ref, after)

    if len(entries) > 0:
        if output:
            parent = os.path.dirname(output)
            if parent != "":
                os.makedirs(parent, exist_ok=True)
            with open(output, "a", encoding="utf-8") as file:
                write_csv(
                    entries, file, entries[0].__class__, not no_headers, repository_name
                )
        else:
            write_csv(
                entries,
                sys.stdout,
                entries[0].__class__,
                not no_headers,
                repository_name,
            )

    if tmp_directory:
        tmp_directory.cleanup()
    if len(entries) == 0 and delete_if_no_entries:
        print("Detected no entries, deleting")
        if save_repository:
            shutil.rmtree(save_repository)
        elif os.path.exists(repository):
            shutil.rmtree(repository)


if __name__ == "__main__":
    main()
