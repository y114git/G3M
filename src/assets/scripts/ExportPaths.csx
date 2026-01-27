


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

string pathsOut = GetOutputDirectory();
PrintLine($"[ExportPaths] Exporting to: {pathsOut}");

List<UndertalePath> allPaths = Data.Paths?.ToList() ?? new List<UndertalePath>();
PrintLine($"[ExportPaths] Found {allPaths.Count} paths to export.");

SetProgressBar(null, "Exporting Paths", 0, allPaths.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allPaths, p => ExportPath(p, pathsOut)));

void ExportPath(UndertalePath path, string outputDir)
{
    if (path?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(path.Name.Content);
        string jsonPath = Path.Combine(outputDir, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", path.Name.Content);
            writer.WriteBoolean("isSmooth", path.IsSmooth);
            writer.WriteBoolean("isClosed", path.IsClosed);
            writer.WriteNumber("precision", (int)path.Precision);

            writer.WriteStartArray("points");
            foreach (var point in path.Points)
            {
                writer.WriteStartObject();
                writer.WriteNumber("x", point.X);
                writer.WriteNumber("y", point.Y);
                writer.WriteNumber("speed", point.Speed);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportPaths] Failed to export path {path.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportPaths] Export complete. {allPaths.Count} paths exported to {pathsOut}");
