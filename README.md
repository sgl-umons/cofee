# cofee

---

An automated tool for extracting files from Git repositories written in Python.
`cofee` (**CO**ntext **F**ile **E**xtraction **E**ngine) is designed to be used as a CLI-tool.
Given a Git repository, it traverses its history respecting the first-parent rule until the first commit (or given reference) is reached.
For each commit, `cofee` checks for any match between the commit modifications and its configuration.
Any file matching one of the glob-like syntax in its configuration is saved in a given directory along with relevant metadata in a given CSV file.

`cofee` was first created to extract context files of well known AI  provider (i.e., Claude, Copilot, Codex, Gemini, Windsurf and Cursor), and we provide a configuration file to do so.
However, you can use `cofee` to extract any files by changing its configuration file, or creating a new one.

This project is developed by Guillaume Cardoen at the Software Engineering Lab of the University of Mons (Belgium).

## Installation

An easy way to install `cofee` is via `pip` from this GitHub repository
```
pip install git+https://github.com/sgl-umons/cofee
```

Alternatively, you can clone this repository and install it locally
```
git clone https://github.com/sgl-umons/cofee
cd cofee
pip install .
```

You may wish to use `cofee` in a virtual environment
```
virtualenv venv
source venv/bin/activate
pip install cofee
```

## Usage

After installation, the `cofee` command-line tool should be available in your shell. You can use `cofee` with the following arguments:

```
Usage: cofee [OPTIONS] REPOSITORY

  Extract the files from a single Git repository `REPOSITORY`. The extraction
  is done by traversing the Git history of the repository starting from the
  reference given to `-r` and going back in time respecting the first-parent
  rule until the first commit (or the reference given to `-a`) is reached. The
  Git repository can be local or distant. In the latter case, it will be
  pulled locally and deleted unless specified otherwise. Every extracted file
  will be stored in the directory given to `-f` (or the directory `files` if
  not specified). The metadata related to the extracted files will be written
  in the CSV file given to `-o`, or in the standard output if not specified.

  Example of usage: cofee https://github.com/sgl-umons/cofee -c config.toml

Options:
  -r, --ref, --branch REF         The most recent commit reference (i.e.,
                                  commit SHA or TAG) to be considered for the
                                  extraction.
  -s, --save-repository DIRECTORY
                                  Save the repository to the given directory
                                  in case `REPOSITORY` was distant.
  --delete-if-no-entries          In case --save-repository/-s was given or if
                                  the repository is local, delete the
                                  repository if no entries were generated from
                                  this repository.
  -u, --update                    Fetch the repository at the given path.
  -a, --after REF                 Only consider commits after the given commit
                                  reference (i.e., commit SHA or TAG).
  -f, --files DIRECTORY           The directory where the extracted files will
                                  be stored.
  -o, --output FILE               The output CSV file where information
                                  related to the dataset will be stored. By
                                  default, the information will written to the
                                  standard output.
  -n, --repository-name TEXT      Add a column `repository` to the output file
                                  where each value will be equal to the
                                  provided parameter.
  --no-headers                    Remove the header row from the CSV output
                                  file.
  -c, --config FILE               Configuration files for the different
                                  filters
  -h, --help                      Show this message and exit.
```

The CSV file given to `-o` (or that will be written to the standard output by default) will contain the following columns:

- `repository`: The repository (author and repository name) from which the context file was extracted. The separator "/" allows to distinguish between the author and the repository name
- `agent_name`: The agent group (e.g., claude) to which the file belongs to.
- `category`: The file category (i.e., context, skill or subagent) to which the file belongs to.
- `commit_hash`: The commit hash returned by git
- `author_name`: The name of the author that changed this file
- `author_email`: The email of the author that changed this file
- `committer_name`: The name of the committer
- `committer_email`: The email of the committer
- `committed_date`: The committed date of the commit
- `authored_date`:  The authored date of the commit
- `file_path`:  The path to this file in the repository
- `previous_file_path`: The path to this file before it has been touched
- `file_hash`: The name of the related workflow file in the dataset.
- `previous_file_hash`: The name of the related workflow file in the dataset, before it has been touched
- `git_change_type`: A single letter (A,D, M or R) representing the type of change made to the workflow (Added, Deleted, Modified or Renamed). This letter is given by gitpython and provided as is. This can be unreliable to detect addition or deletion of a file in the scope of the dataset. Please use file_hash and previous_file_hash to detect the addition or deletion of a file in the scope of this dataset.
- `uid`: Unique identifier for a given file surviving modifications and renames. It is generated on the addition of the file and stays the same until the file is deleted. Renamings does not change the identifier.
- `symbolic_link`: A boolean flag signaling whether the file is a symbolic link (i.e., a pointer or alias to another file).
- `previous_symbolic_link`: A boolean flag signaling whether the file was a symbolic link before it was touched.

### Examples

As an example, the following command will fetch The GitHub repository `https://github.com/sgl-umons/cofee`, and save under the `cofee_repository` directory and the `repository` column will be `cofee` in the resulting CSV file. Note that, if `-s cofee` was not specified, the tool will create a temporary directory and clean up when it finishes.

```bash
cofee https://github.com/sgl-umons/cofee -n cofee -s cofee_repository -o output.csv
```
