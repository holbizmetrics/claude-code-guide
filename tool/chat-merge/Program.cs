using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;

namespace ChatMerge;

/// <summary>
/// Merges multiple exported chat files that contain overlapping content
/// (progressive exports of the same conversation) into a single deduplicated output.
/// </summary>
class Program
{
    static int Main(string[] args)
    {
        string outputFile = "";
        bool singleMode = false;
        var txtFiles = new List<string>();

        // Parse args: supports directory, glob pattern, -o output, or individual files
        // Usage:
        //   ChatMerge <directory>                          — all .txt in directory
        //   ChatMerge <directory> <pattern>                — glob pattern in directory
        //   ChatMerge <directory/pattern>                  — glob pattern (e.g. "dir/*lab*.txt")
        //   ChatMerge <file1> <file2> ...                  — explicit file list
        //   -o <output>                                    — output file (optional, anywhere in args)
        //   --single                                       — merge all streams into one file
        var positionalArgs = new List<string>();
        for (int i = 0; i < args.Length; i++)
        {
            if (args[i] == "-o" && i + 1 < args.Length)
            {
                outputFile = args[++i];
            }
            else if (args[i] is "--single" or "-s")
            {
                singleMode = true;
            }
            else
            {
                positionalArgs.Add(args[i]);
            }
        }

        if (positionalArgs.Count == 0)
        {
            Console.Write("Input (directory, glob pattern, or files): ");
            var input = Console.ReadLine()?.Trim().Trim('"') ?? "";
            positionalArgs.Add(input);
        }

        txtFiles = ResolveInputFiles(positionalArgs);

        if (txtFiles.Count == 0)
        {
            Console.Error.WriteLine("No matching files found.");
            Console.Error.WriteLine();
            Console.Error.WriteLine("ChatMerge — merge overlapping chat exports into deduplicated output.");
            Console.Error.WriteLine();
            Console.Error.WriteLine("Auto-detects progressive exports (same conversation exported at different");
            Console.Error.WriteLine("times), groups them into streams, and writes one merged file per stream.");
            Console.Error.WriteLine();
            Console.Error.WriteLine("Usage:");
            Console.Error.WriteLine("  ChatMerge <directory>                    — all .txt files in directory");
            Console.Error.WriteLine("  ChatMerge <directory> \"*lab*.txt\"         — glob pattern in directory");
            Console.Error.WriteLine("  ChatMerge \"path/to/*lab*.txt\"             — glob pattern with path");
            Console.Error.WriteLine("  ChatMerge file1.txt file2.txt file3.txt  — explicit files");
            Console.Error.WriteLine();
            Console.Error.WriteLine("Options:");
            Console.Error.WriteLine("  --single, -s       Merge all streams into one deduplicated file");
            Console.Error.WriteLine("  -o <file>          Output file (only with --single or single stream)");
            return 1;
        }

        // outputFile remains "" if -o was not specified; resolved per-mode below

        Console.WriteLine($"Found {txtFiles.Count} files:");

        // Step 1: Read all files into line arrays
        var fileLines = new Dictionary<string, string[]>();
        foreach (var f in txtFiles)
        {
            var lines = File.ReadAllLines(f);
            fileLines[f] = lines;
            Console.WriteLine($"  {Path.GetFileName(f)}: {lines.Length} lines");
        }

        // Step 2: Group files into "streams" — detect progressive exports
        // (file A is a prefix of file B = same conversation exported at different times)
        var groups = GroupProgressiveExports(fileLines);

        // Warn about singleton files that didn't group with anything
        var singletonFiles = groups
            .Where(g => g.Files.Count == 1)
            .Select(g => g.Files[0])
            .ToList();
        if (singletonFiles.Count > 0 && groups.Count > 1)
        {
            Console.WriteLine($"\nNote: {singletonFiles.Count} file(s) didn't match any other stream:");
            foreach (var f in singletonFiles)
                Console.WriteLine($"  {Path.GetFileName(f)} — will be output as its own stream");
            Console.WriteLine("  (If these aren't chat exports, consider using a glob pattern to exclude them)");
        }

        Console.WriteLine($"\nDetected {groups.Count} conversation stream(s):");
        foreach (var (groupName, files) in groups)
        {
            Console.WriteLine($"  Stream: {groupName}");
            foreach (var f in files)
                Console.WriteLine($"    {Path.GetFileName(f)} ({fileLines[f].Length} lines)");
        }

        // Step 3: For each group, keep only the largest file (contains all earlier content)
        var streamResults = new List<(string StreamName, string LargestFile, string[] Lines)>();
        foreach (var (groupName, files) in groups)
        {
            var largest = files.OrderByDescending(f => fileLines[f].Length).First();
            Console.WriteLine($"  Keeping: {Path.GetFileName(largest)} ({fileLines[largest].Length} lines)");

            // Derive stream name: find the common prefix of all filenames in the group
            var streamName = GetCommonPrefix(files.Select(Path.GetFileNameWithoutExtension).ToList());
            streamResults.Add((streamName, largest, fileLines[largest]));
        }

        // Step 4: Write output
        Console.WriteLine();
        var outputDir = Path.GetDirectoryName(txtFiles[0]) ?? ".";

        if (singleMode)
        {
            // --single: merge all streams into one cross-deduplicated file
            if (string.IsNullOrEmpty(outputFile))
                outputFile = Path.Combine(outputDir, "_merged_output.txt");

            var allStreams = streamResults.Select(s => s.Lines).ToList();
            var totalInput = allStreams.Sum(s => s.Length);
            var merged = MergeStreams(allStreams);
            var deduplicated = totalInput - merged.Count;

            File.WriteAllLines(outputFile, merged);
            Console.WriteLine($"Merged all {groups.Count} stream(s) into single file:");
            Console.WriteLine($"  {totalInput} input lines → {merged.Count} output lines ({deduplicated} deduplicated)");
            Console.WriteLine($"  Written to: {outputFile}");
        }
        else
        {
            // Default: one file per stream, auto-named <common-prefix>_merged.txt
            if (!string.IsNullOrEmpty(outputFile) && groups.Count > 1)
            {
                Console.WriteLine($"Note: -o ignored in multi-stream mode ({groups.Count} streams detected).");
                Console.WriteLine($"  Use --single to merge all into one file, or omit -o for auto-named output.");
                Console.WriteLine();
            }

            foreach (var (streamName, _, lines) in streamResults)
            {
                var outPath = !string.IsNullOrEmpty(outputFile) && streamResults.Count == 1
                    ? outputFile
                    : Path.Combine(outputDir, $"{streamName}_merged.txt");
                File.WriteAllLines(outPath, lines);
                Console.WriteLine($"Stream \"{streamName}\":");
                Console.WriteLine($"  {lines.Length} lines → {outPath}");
            }
        }

        return 0;
    }

    /// <summary>
    /// Finds the longest common prefix of a list of filenames (without extension),
    /// trimmed of trailing digits, hyphens, and underscores.
    /// e.g. ["full-prometheus-crystal-lab-chat-export-1", "...-2", "...-3", "...-4"]
    ///   → "full-prometheus-crystal-lab-chat-export"
    /// </summary>
    static string GetCommonPrefix(List<string?> names)
    {
        var clean = names.Where(n => !string.IsNullOrEmpty(n)).Select(n => n!).ToList();
        if (clean.Count == 0) return "merged";
        if (clean.Count == 1) return clean[0];

        var sorted = clean.OrderBy(n => n).ToList();
        var first = sorted[0];
        var last = sorted[^1];

        int commonLen = 0;
        for (int i = 0; i < Math.Min(first.Length, last.Length); i++)
        {
            if (first[i] == last[i])
                commonLen = i + 1;
            else
                break;
        }

        var prefix = first[..commonLen];

        // Trim trailing separators and digits: "export-" → "export"
        prefix = prefix.TrimEnd('-', '_', ' ', '.');

        return string.IsNullOrWhiteSpace(prefix) ? "merged" : prefix;
    }

    /// <summary>
    /// Resolves positional args into a list of .txt file paths.
    /// Supports: directory, directory + pattern, glob with path, or explicit files.
    /// </summary>
    static List<string> ResolveInputFiles(List<string> positionalArgs)
    {
        var result = new List<string>();

        if (positionalArgs.Count == 1)
        {
            var arg = positionalArgs[0];

            if (Directory.Exists(arg))
            {
                // Bare directory — all .txt files
                result.AddRange(Directory.GetFiles(arg, "*.txt"));
            }
            else if (ContainsGlobChars(arg))
            {
                // Glob pattern like "path/to/*lab*.txt"
                result.AddRange(ExpandGlob(arg));
            }
            else if (File.Exists(arg))
            {
                result.Add(Path.GetFullPath(arg));
            }
        }
        else if (positionalArgs.Count == 2
                 && Directory.Exists(positionalArgs[0])
                 && ContainsGlobChars(positionalArgs[1]))
        {
            // Directory + pattern: ChatMerge "some dir" "*lab*.txt"
            var dir = positionalArgs[0];
            var pattern = positionalArgs[1];
            result.AddRange(Directory.GetFiles(dir, pattern));
        }
        else
        {
            // Multiple args — treat each as a file or glob
            foreach (var arg in positionalArgs)
            {
                if (File.Exists(arg))
                    result.Add(Path.GetFullPath(arg));
                else if (ContainsGlobChars(arg))
                    result.AddRange(ExpandGlob(arg));
                else if (Directory.Exists(arg))
                    result.AddRange(Directory.GetFiles(arg, "*.txt"));
            }
        }

        return result
            .Where(f => !Path.GetFileName(f).StartsWith("_")
                      && !Path.GetFileNameWithoutExtension(f).EndsWith("_merged")) // skip our own output
            .OrderBy(f => f)
            .ToList();
    }

    static bool ContainsGlobChars(string s) => s.Contains('*') || s.Contains('?');

    /// <summary>
    /// Expands a glob pattern like "path/to/*lab*.txt" by splitting into directory + pattern.
    /// </summary>
    static List<string> ExpandGlob(string globPattern)
    {
        // Split into directory part and filename pattern
        var dir = Path.GetDirectoryName(globPattern);
        var pattern = Path.GetFileName(globPattern);

        if (string.IsNullOrEmpty(dir))
            dir = ".";
        if (string.IsNullOrEmpty(pattern))
            pattern = "*.txt";

        if (!Directory.Exists(dir))
            return new List<string>();

        return Directory.GetFiles(dir, pattern).ToList();
    }

    /// <summary>
    /// Groups files that are progressive exports of the same conversation.
    /// Two files belong to the same group if the smaller one's beginning matches the larger one's.
    /// </summary>
    static List<(string GroupName, List<string> Files)> GroupProgressiveExports(
        Dictionary<string, string[]> fileLines)
    {
        var files = fileLines.Keys.OrderBy(f => fileLines[f].Length).ToList();
        var groupMap = new Dictionary<string, int>();
        for (int i = 0; i < files.Count; i++)
            groupMap[files[i]] = i;

        for (int i = 0; i < files.Count; i++)
        {
            for (int j = i + 1; j < files.Count; j++)
            {
                if (groupMap[files[i]] == groupMap[files[j]])
                    continue;

                if (IsPrefixOf(fileLines[files[i]], fileLines[files[j]]))
                {
                    int oldGroup = groupMap[files[i]];
                    int newGroup = groupMap[files[j]];
                    foreach (var key in groupMap.Keys.ToList())
                    {
                        if (groupMap[key] == oldGroup)
                            groupMap[key] = newGroup;
                    }
                }
            }
        }

        var groupSets = new Dictionary<int, List<string>>();
        foreach (var (file, gid) in groupMap)
        {
            if (!groupSets.ContainsKey(gid))
                groupSets[gid] = new List<string>();
            groupSets[gid].Add(file);
        }

        var groups = new List<(string, List<string>)>();
        foreach (var (_, gFiles) in groupSets.OrderBy(g => g.Key))
        {
            var name = Path.GetFileNameWithoutExtension(gFiles.OrderBy(f => f).First());
            groups.Add((name, gFiles));
        }
        return groups;
    }

    /// <summary>
    /// Checks if smaller is a prefix-export of larger by 5-line window fingerprint match.
    /// Robust to line-wrap drift caused by working-directory path differences in exports
    /// (a longer absolute path wraps onto an extra terminal line, shifting all subsequent
    /// line numbers — position-aligned matching breaks; window-fingerprint matching does not).
    /// </summary>
    static bool IsPrefixOf(string[] smaller, string[] larger)
    {
        if (smaller.Length > larger.Length) return false;
        int checkLen = Math.Min(smaller.Length, 200);
        if (checkLen < 5) return false;

        // Allow ±50 lines of slack in larger to absorb wrap drift across exports
        int largerWindow = Math.Min(larger.Length, checkLen + 50);
        var largerFps = new HashSet<string>();
        for (int i = 0; i + 5 <= largerWindow; i++)
            largerFps.Add(GetWindowFingerprint(larger, i, 5));

        int matches = 0, total = 0;
        for (int i = 0; i + 5 <= checkLen; i++)
        {
            total++;
            if (largerFps.Contains(GetWindowFingerprint(smaller, i, 5)))
                matches++;
        }
        return total > 0 && matches > total * 0.85;
    }

    /// <summary>
    /// Merges conversation streams, removing duplicate blocks across streams.
    /// </summary>
    static List<string> MergeStreams(List<string[]> streams)
    {
        if (streams.Count == 1)
            return streams[0].ToList();

        // Use the longest stream as base
        var ordered = streams.OrderByDescending(s => s.Length).ToList();
        var result = new List<string>(ordered[0]);
        var baseFingerprints = BuildFingerprints(ordered[0], 5);

        for (int s = 1; s < ordered.Count; s++)
        {
            var stream = ordered[s];
            var uniqueRanges = FindUniqueRanges(stream, baseFingerprints, 5);

            if (uniqueRanges.Count > 0)
            {
                int uniqueLines = uniqueRanges.Sum(r => r.End - r.Start + 1);
                int dupLines = stream.Length - uniqueLines;
                Console.WriteLine($"  Stream {s + 1}: {stream.Length} lines → {uniqueLines} unique, {dupLines} deduplicated");

                result.Add("");
                result.Add("═══════════════════════════════════════════════════════════════");
                result.Add($"══ Additional content from conversation stream {s + 1} ══");
                result.Add("═══════════════════════════════════════════════════════════════");
                result.Add("");

                foreach (var (start, end) in uniqueRanges)
                {
                    for (int i = start; i <= end; i++)
                        result.Add(stream[i]);
                }

                // Add this unique content to fingerprints so subsequent streams dedup against it too
                foreach (var (start, end) in uniqueRanges)
                {
                    for (int i = start; i <= Math.Min(end, stream.Length - 5); i++)
                    {
                        var fp = GetWindowFingerprint(stream, i, 5);
                        baseFingerprints.Add(fp);
                    }
                    for (int i = start; i <= end; i++)
                    {
                        var norm = NormalizeLine(stream[i]);
                        if (norm.Length > 20)
                            baseFingerprints.Add("LINE:" + norm);
                    }
                }
            }
            else
            {
                Console.WriteLine($"  Stream {s + 1}: fully contained in base — skipping");
            }
        }

        return result;
    }

    static HashSet<string> BuildFingerprints(string[] lines, int windowSize)
    {
        var fps = new HashSet<string>();
        for (int i = 0; i <= lines.Length - windowSize; i++)
        {
            fps.Add(GetWindowFingerprint(lines, i, windowSize));
        }
        foreach (var line in lines)
        {
            var norm = NormalizeLine(line);
            if (norm.Length > 20)
                fps.Add("LINE:" + norm);
        }
        return fps;
    }

    /// <summary>
    /// Find ranges of lines NOT present in the base fingerprints.
    /// </summary>
    static List<(int Start, int End)> FindUniqueRanges(
        string[] stream, HashSet<string> baseFingerprints, int windowSize)
    {
        var isDuplicate = new bool[stream.Length];

        // Check sliding windows
        for (int i = 0; i <= stream.Length - windowSize; i++)
        {
            var fp = GetWindowFingerprint(stream, i, windowSize);
            if (baseFingerprints.Contains(fp))
            {
                for (int j = i; j < i + windowSize; j++)
                    isDuplicate[j] = true;
            }
        }

        // Check individual substantial lines
        for (int i = 0; i < stream.Length; i++)
        {
            var norm = NormalizeLine(stream[i]);
            if (norm.Length > 20 && baseFingerprints.Contains("LINE:" + norm))
                isDuplicate[i] = true;
        }

        // Mark orphaned blank lines between duplicate blocks
        for (int i = 0; i < stream.Length; i++)
        {
            if (string.IsNullOrWhiteSpace(stream[i]))
            {
                bool prevDup = i > 0 && isDuplicate[i - 1];
                bool nextDup = i < stream.Length - 1 && isDuplicate[i + 1];
                if (prevDup && nextDup)
                    isDuplicate[i] = true;
            }
        }

        // Extract contiguous unique ranges with substantial content
        var ranges = new List<(int, int)>();
        int? rangeStart = null;

        for (int i = 0; i < stream.Length; i++)
        {
            if (!isDuplicate[i])
            {
                rangeStart ??= i;
            }
            else if (rangeStart.HasValue)
            {
                if (HasSubstantialContent(stream, rangeStart.Value, i - 1))
                    ranges.Add((rangeStart.Value, i - 1));
                rangeStart = null;
            }
        }
        if (rangeStart.HasValue && HasSubstantialContent(stream, rangeStart.Value, stream.Length - 1))
            ranges.Add((rangeStart.Value, stream.Length - 1));

        return ranges;
    }

    static bool HasSubstantialContent(string[] lines, int start, int end)
    {
        for (int i = start; i <= end; i++)
        {
            if (!string.IsNullOrWhiteSpace(lines[i]) && lines[i].Trim().Length > 5)
                return true;
        }
        return false;
    }

    static string GetWindowFingerprint(string[] lines, int start, int size)
    {
        var sb = new StringBuilder();
        for (int i = start; i < start + size && i < lines.Length; i++)
        {
            sb.Append(NormalizeLine(lines[i]));
            sb.Append('\n');
        }
        return sb.ToString();
    }

    static string NormalizeLine(string line)
    {
        var normalized = string.Join(' ', line.Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));
        if (normalized.Length == 0) return "";

        // Canonicalize Claude Code rendering noise that varies across exports of the same conversation:
        //   spinner verb ("Brewed"/"Churned"/"Cogitated"/...), CLI version, model line, working-directory banner.
        if (normalized.StartsWith("✻ "))                              // ✻ <Verb> for Ns
            return "✻ <STATUS>";
        if (normalized.StartsWith("▐▛███▜▌")) // ▐▛███▜▌ Claude Code vX.Y.Z
            return "<CC-BANNER-VERSION>";
        if (normalized.StartsWith("▝▜█████▛▘")) // ▝▜█████▛▘ <model>
            return "<CC-BANNER-MODEL>";
        if (normalized.StartsWith("▘▘ ▝▝"))            // ▘▘ ▝▝ <workdir>
            return "<CC-BANNER-WORKDIR>";

        return normalized;
    }
}
