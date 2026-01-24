


using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;




string OutputDirectory = "";




void PrintLine(string s) => Console.WriteLine(s);

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string ResolveOutputDirectory()
{
    if (!string.IsNullOrEmpty(OutputDirectory) && Directory.Exists(OutputDirectory))
        return OutputDirectory;

    if (string.IsNullOrEmpty(FilePath))
        throw new ScriptException("No data.win file loaded. Please load a game data file first.");

    string dataWinDir = Path.GetDirectoryName(FilePath);
    string outputDir = Path.Combine(dataWinDir, "Objects", "Timelines");
    Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

string timelinesOut = ResolveOutputDirectory();
PrintLine($"[ExportTimelines] Exporting to: {timelinesOut}");

List<UndertaleTimeline> allTimelines = Data.Timelines?.ToList() ?? new List<UndertaleTimeline>();
PrintLine($"[ExportTimelines] Found {allTimelines.Count} timelines to export.");

SetProgressBar(null, "Exporting Timelines", 0, allTimelines.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allTimelines, tl => ExportTimeline(tl, timelinesOut)));

void ExportTimeline(UndertaleTimeline timeline, string outputDir)
{
    if (timeline?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(timeline.Name.Content);
        string jsonPath = Path.Combine(outputDir, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", timeline.Name.Content);

            writer.WriteStartArray("moments");
            foreach (var moment in timeline.Moments)
            {
                writer.WriteStartObject();
                writer.WriteNumber("step", (int)moment.Step);

                if (moment.Event != null && moment.Event.Count > 0)
                {
                    writer.WriteStartArray("actions");
                    foreach (var action in moment.Event)
                    {
                        writer.WriteStartObject();
                        if (action.CodeId?.Name?.Content != null)
                            writer.WriteString("codeId", action.CodeId.Name.Content);
                        else
                            writer.WriteNull("codeId");
                        writer.WriteNumber("libId", action.LibID);
                        writer.WriteNumber("id", action.ID);
                        writer.WriteNumber("kind", action.Kind);
                        writer.WriteBoolean("useRelative", action.UseRelative);
                        writer.WriteBoolean("isQuestion", action.IsQuestion);
                        writer.WriteBoolean("useApplyTo", action.UseApplyTo);
                        writer.WriteNumber("exeType", action.ExeType);
                        writer.WriteString("actionName", action.ActionName?.Content ?? "");
                        writer.WriteNumber("argumentCount", action.ArgumentCount);
                        writer.WriteNumber("who", action.Who);
                        writer.WriteBoolean("relative", action.Relative);
                        writer.WriteBoolean("isNot", action.IsNot);
                        writer.WriteEndObject();
                    }
                    writer.WriteEndArray();
                }

                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportTimelines] Failed to export timeline {timeline.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportTimelines] Export complete. {allTimelines.Count} timelines exported to {timelinesOut}");
