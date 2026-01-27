


using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;




void PrintLine(string s) => Console.WriteLine(s);

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string GetOutputDirectory()
{
    string outputDir = Environment.GetEnvironmentVariable("OUTPUT_DIR");
    if (string.IsNullOrEmpty(outputDir))
        throw new ScriptException("OUTPUT_DIR environment variable is not set.");
    if (!Directory.Exists(outputDir))
        Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

string audioGroupsOut = GetOutputDirectory();
PrintLine($"[ExportAudioGroups] Exporting to: {audioGroupsOut}");

List<UndertaleAudioGroup> allAudioGroups = Data.AudioGroups?.ToList() ?? new List<UndertaleAudioGroup>();
PrintLine($"[ExportAudioGroups] Found {allAudioGroups.Count} audio groups to export.");

SetProgressBar(null, "Exporting Audio Groups", 0, allAudioGroups.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allAudioGroups, ag => ExportAudioGroup(ag, audioGroupsOut)));

void ExportAudioGroup(UndertaleAudioGroup audioGroup, string outputDir)
{
    if (audioGroup?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(audioGroup.Name.Content);
        string jsonPath = Path.Combine(outputDir, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", audioGroup.Name.Content);
            if (audioGroup.Path != null)
                writer.WriteString("path", audioGroup.Path.Content ?? "");
            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAudioGroups] Failed to export audio group {audioGroup.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportAudioGroups] Export complete. {allAudioGroups.Count} audio groups exported to {audioGroupsOut}");
