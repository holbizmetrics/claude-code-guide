# ChatMerge

Merge multiple exported chat files that contain overlapping content (progressive
exports of the same conversation) into a single deduplicated output.

Two chats from the same session, exported at different points in time, share a
common prefix. ChatMerge auto-detects these progressive exports, groups them
into streams, and writes one merged file per stream — keeping the largest
member of each group.

## Build

Requires the .NET 10 SDK.

```sh
dotnet build
```

The binary lands at `bin/Debug/net10.0/ChatMerge` (or `ChatMerge.exe` on
Windows). Cross-platform: builds and runs on Windows, macOS, and Linux without
modification.

For a self-contained binary that runs without the SDK installed:

```sh
dotnet publish -c Release -r osx-arm64 --self-contained
dotnet publish -c Release -r linux-x64 --self-contained
dotnet publish -c Release -r win-x64   --self-contained
```

## Usage

```
ChatMerge <directory>                 — all .txt files in directory
ChatMerge <directory> "*lab*.txt"     — glob pattern in directory
ChatMerge "path/to/*lab*.txt"         — glob pattern with path
ChatMerge file1.txt file2.txt ...     — explicit files
```

Options:

```
--single, -s       Merge all streams into one deduplicated file
-o <file>          Output file (only with --single or single stream)
```

By default, writes one `<common-prefix>_merged.txt` per detected stream
alongside the inputs.

## How it groups

Two files belong to the same stream if the smaller's first ~200 lines match
the larger's first ~250 lines at 85%+ via 5-line window fingerprints.

Window-fingerprint matching (rather than position-aligned comparison) is
robust to terminal line-wrap drift — exports of the same Claude Code
conversation can differ in line numbering when working-directory paths render
at different lengths and wrap onto different numbers of terminal lines. The
fingerprint approach absorbs this drift; position-aligned comparison does not.

`NormalizeLine` also canonicalizes Claude Code rendering noise that varies
between exports of the same conversation: the spinner verb (`✻ Brewed for`,
`✻ Cogitated for`, `✻ Cooked for`, `✻ Sautéed for`, ...), the version banner,
the model line, and the working-directory line.

## Limitations

- **Post-compact tails**: when a conversation is compacted and additional
  turns are exported as a separate file, that tail does *not* share a prefix
  with the pre-compact captures. ChatMerge correctly leaves it as its own
  stream. A future "stitch" operation could concatenate post-compact tails
  onto their pre-compact stream; not implemented.
- Detection heuristic for the post-compact case: the tail file starts with
  `✻ Conversation compacted` at line 5 instead of a `>` user prompt.

## See also

- `../claude-chat.py` — Python utility for working with Claude Code's local
  JSONL session transcripts (list / search / export / backup / extract). A
  Python port of the merge logic may eventually land there as a `merge`
  subcommand.
