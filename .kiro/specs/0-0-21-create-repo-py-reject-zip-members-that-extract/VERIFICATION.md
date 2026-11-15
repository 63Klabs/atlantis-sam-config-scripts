# Test

## Windows:

### Run against unsafe-backslash.zip

UI/CLI

```
Creating CodeCommit repository: test_chadkluck-win01
CodeCommit Repository created: https://git-codecommit.us-east-2.amazonaws.com/v1/repos/test_chadkluck-win01
Creating initial README.md on main branch 
Creating test branch from main 
Creating dev branch from test 
Successfully created branch structure 
Downloading zip from S3: s3://63klabz/atlantis/app-starters/v2/unsafe-backslash.zip
Unsafe source zip: zip member '../outside-test.txt' resolves outside the extraction directory. Nothing was seeded. 
Repository test_chadkluck-win01 deleted. 
```

Logs

```
2026-11-15 12:36:40,890 - INFO - ['./cli/create_repo.py', 'test_chadkluck-win01', '--profile', 'labs']
2026-11-15 12:36:40,890 - INFO - Version: v0.2.6/2026-11-15
2026-11-15 12:36:40,895 - INFO - Using AWS profile: labs
2026-11-15 12:36:42,093 - INFO - Using existing valid credentials
2026-11-15 12:36:42,208 - INFO - Loaded config from 'C:\Users\clkluck\Projects\personal\aws\labs\sam-config-labs\defaults\defaults.json'
2026-11-15 12:36:42,431 - INFO - Discovering app starters from s3://63klabs/atlantis/app-starters/v2
2026-11-15 12:36:42,621 - INFO - Discovering app starters from s3://63klabz/atlantis/app-starters/v2
2026-11-15 12:37:04,294 - INFO - Creating CodeCommit repository: test_chadkluck-win01
2026-11-15 12:37:04,640 - INFO - CodeCommit Repository created: https://git-codecommit.us-east-2.amazonaws.com/v1/repos/test_chadkluck-win01
2026-11-15 12:37:04,752 - INFO - Creating initial README.md on main branch
2026-11-15 12:37:04,850 - WARNING - Using secondary option to crate initial commit
2026-11-15 12:37:05,973 - INFO - Creating test branch from main
2026-11-15 12:37:06,135 - INFO - Creating dev branch from test
2026-11-15 12:37:06,307 - INFO - Successfully created branch structure
2026-11-15 12:37:06,308 - INFO - Downloading zip from S3: s3://63klabz/atlantis/app-starters/v2/unsafe-backslash.zip
2026-11-15 12:37:06,448 - ERROR - Unsafe source zip rejected: zip member '../outside-test.txt' resolves outside the extraction directory
2026-11-15 12:37:06,673 - INFO - Deleted failed repository: test_chadkluck-win01
```

### Run against unsafe-slash.zip

CLI/UI

```
Creating CodeCommit repository: test_chadkluck-win01
CodeCommit Repository created: https://git-codecommit.us-east-2.amazonaws.com/v1/repos/test_chadkluck-win01
Creating initial README.md on main branch 
Creating test branch from main 
Creating dev branch from test 
Successfully created branch structure 
Downloading zip from S3: s3://63klabz/atlantis/app-starters/v2/unsafe-slash.zip
Unsafe source zip: zip member '../outside-test.txt' resolves outside the extraction directory. Nothing was seeded. 
Repository test_chadkluck-win01 deleted. 
```

LOGS

```
2026-11-15 12:39:09,749 - INFO - ['./cli/create_repo.py', 'test_chadkluck-win01', '--profile', 'labs']
2026-11-15 12:39:09,749 - INFO - Version: v0.2.6/2026-11-15
2026-11-15 12:39:09,753 - INFO - Using AWS profile: labs
2026-11-15 12:39:10,778 - INFO - Using existing valid credentials
2026-11-15 12:39:10,873 - INFO - Loaded config from 'C:\Users\clkluck\Projects\personal\aws\labs\sam-config-labs\defaults\defaults.json'
2026-11-15 12:39:11,083 - INFO - Discovering app starters from s3://63klabs/atlantis/app-starters/v2
2026-11-15 12:39:11,256 - INFO - Discovering app starters from s3://63klabz/atlantis/app-starters/v2
2026-11-15 12:39:23,199 - INFO - Creating CodeCommit repository: test_chadkluck-win01
2026-11-15 12:39:23,512 - INFO - CodeCommit Repository created: https://git-codecommit.us-east-2.amazonaws.com/v1/repos/test_chadkluck-win01
2026-11-15 12:39:23,630 - INFO - Creating initial README.md on main branch
2026-11-15 12:39:23,738 - WARNING - Using secondary option to crate initial commit
2026-11-15 12:39:24,723 - INFO - Creating test branch from main
2026-11-15 12:39:24,926 - INFO - Creating dev branch from test
2026-11-15 12:39:25,075 - INFO - Successfully created branch structure
2026-11-15 12:39:25,077 - INFO - Downloading zip from S3: s3://63klabz/atlantis/app-starters/v2/unsafe-slash.zip
2026-11-15 12:39:25,220 - ERROR - Unsafe source zip rejected: zip member '../outside-test.txt' resolves outside the extraction directory
2026-11-15 12:39:25,340 - INFO - Deleted failed repository: test_chadkluck-win01
```

### Further tests

Results of 3 clean up actions:

ls: cannot access '/tmp/outside-test.txt': No such file or directory

exit status: 1

An error occurred (RepositoryDoesNotExistException) when calling the GetRepository operation: test_chadkluck-win01

Original zip files deleted.