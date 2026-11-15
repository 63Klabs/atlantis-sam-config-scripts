# Manual tests

## Windows w/ GitBash

### Github

Create repository using zip
Successfully created
Can successfully check out dev, test, and main
dev and test contain 
- .gitignore CRLF
- notes.txt with special characters ISO 8859-1
- README.md
- logo.png a smiling face on a white background

```
Cloning into 'test_chad_win6'...
remote: Enumerating objects: 8, done.
remote: Counting objects: 100% (8/8), done.
remote: Compressing objects: 100% (5/5), done.
remote: Total 8 (delta 0), reused 8 (delta 0), pack-reused 0 (from 0)
Receiving objects: 100% (8/8), done.
```

sha:

```
dev logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e *-
dev notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c *-
dev README.md   35e022dc2b2cde503884a4124d14de1476202de3b9c73599035c75adc720b9dd *-
dev .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858 *-
test logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e *-
test notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c *-
test README.md   35e022dc2b2cde503884a4124d14de1476202de3b9c73599035c75adc720b9dd *-
test .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858 *-
```

line endings:

```
/dev/stdin: ASCII text
i/crlf  w/crlf  attr/                   .gitignore
i/lf    w/crlf  attr/                   README.md
i/-text w/-text attr/                   logo.png
i/lf    w/crlf  attr/                   notes.txt
```

### CodeCommit

Create repository using zip
Successfully created and cloned

```
Cloning into 'test_chad_win7'...
remote: Counting objects: 8, done.
Unpacking objects: 100% (8/8), 1.14 KiB | 61.00 KiB/s, done.
```

Can successfully check out dev, test, and main
dev and test contain 
- .gitignore CRLF
- notes.txt with special characters ISO 8859-1
- README.md
- logo.png a smiling face on a white background

```
dev logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e *-
dev notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c *-
dev README.md   4bda74ac518232669ff8acec01cfd93caa0be8b7074c9e728fd425b709ded60c *-
dev .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858 *-
test logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e *-
test notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c *-
test README.md   4bda74ac518232669ff8acec01cfd93caa0be8b7074c9e728fd425b709ded60c *-
test .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858 *-
```

line endings:

```
/dev/stdin: ASCII text
i/crlf  w/crlf  attr/                   .gitignore
i/lf    w/crlf  attr/                   README.md
i/-text w/-text attr/                   logo.png
i/lf    w/crlf  attr/                   notes.txt
```

## Linux

### GitHub

Create repository using zip
Successfully created and cloned

```
Cloning into 'test_chad_linux01'...
remote: Enumerating objects: 8, done.
remote: Counting objects: 100% (8/8), done.
remote: Compressing objects: 100% (5/5), done.
remote: Total 8 (delta 1), reused 7 (delta 0), pack-reused 0 (from 0)
Receiving objects: 100% (8/8), done.
Resolving deltas: 100% (1/1), done.
```

Can successfully check out dev, test, and main
dev and test contain 
- .gitignore CRLF
- notes.txt with special characters ISO 8859-1
- README.md
- logo.png a smiling face on a white background

sha

```
dev logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e  -
dev notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c  -
dev README.md   309b459e23f85846a3fb198a82dfa17adda3f7ece83f861cd327f9c895e349b6  -
dev .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858  -
test logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e  -
test notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c  -
test README.md   309b459e23f85846a3fb198a82dfa17adda3f7ece83f861cd327f9c895e349b6  -
test .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858  -
```

line endings

```
/dev/stdin: ASCII text
i/crlf  w/crlf  attr/                   .gitignore
i/lf    w/lf    attr/                   README.md
i/-text w/-text attr/                   logo.png
i/lf    w/lf    attr/                   notes.txt
```

### CodeCommit

Create repository using zip
Successfully created and cloned

```
Cloning into 'test_chad_linux02'...
remote: Counting objects: 8, done.
Unpacking objects: 100% (8/8), 1.14 KiB | 1.14 MiB/s, done.
```

Can successfully check out dev, test, and main
dev and test contain 
- .gitignore CRLF
- notes.txt with special characters ISO 8859-1
- README.md
- logo.png a smiling face on a white background

sha

```
dev logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e  -
dev notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c  -
dev README.md   07d4ec8684695d299d216538ba2c7fd720fc7f753be14142499290d85f90d50b  -
dev .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858  -
test logo.png    544f239bbe21a040342fd2f8954214526747baa3253239b02f4ac5c9f1a77b1e  -
test notes.txt   81592956f9c17d57b1f2c6312e17c4a6b044a41d7e4a7837f50bb7738df6887c  -
test README.md   07d4ec8684695d299d216538ba2c7fd720fc7f753be14142499290d85f90d50b  -
test .gitignore 4143ce57980b9b6ce453057af60af7ca9ba064d5a0434879ed15e3cdc2f26858  -
```

Line endings

```
/dev/stdin: ASCII text
i/crlf  w/crlf  attr/                   .gitignore
i/lf    w/lf    attr/                   README.md
i/-text w/-text attr/                   logo.png
i/lf    w/lf    attr/                   notes.txt
```

## Sha script

```
git fetch origin
for b in dev test; do
  for f in logo.png notes.txt README.md; do
    printf '%s %-11s ' "$b" "$f"
    git show "origin/$b:$f" | sha256sum
  done
done
for b in dev test; do
  printf '%s .gitignore ' "$b"
  MSYS_NO_PATHCONV=1 git show "origin/$b:.gitignore" | sha256sum
done
```