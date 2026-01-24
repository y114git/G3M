


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
    string outputDir = Path.Combine(dataWinDir, "Objects", "Extensions");
    Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

string extensionsOut = ResolveOutputDirectory();
PrintLine($"[ExportExtensions] Exporting to: {extensionsOut}");

List<UndertaleExtension> allExtensions = Data.Extensions?.ToList() ?? new List<UndertaleExtension>();
PrintLine($"[ExportExtensions] Found {allExtensions.Count} extensions to export.");

SetProgressBar(null, "Exporting Extensions", 0, allExtensions.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allExtensions, ext => ExportExtension(ext, extensionsOut)));

void ExportExtension(UndertaleExtension extension, string outputDir)
{
    if (extension?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(extension.Name.Content);
        string jsonPath = Path.Combine(outputDir, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", extension.Name.Content);
            writer.WriteString("folderName", extension.FolderName?.Content ?? "");
            if (extension.Version != null)
                writer.WriteString("version", extension.Version.Content ?? "");
            if (extension.ClassName != null)
                writer.WriteString("className", extension.ClassName.Content ?? "");

            if (extension.Files != null && extension.Files.Count > 0)
            {
                writer.WriteStartArray("files");
                foreach (var file in extension.Files)
                {
                    writer.WriteStartObject();
                    writer.WriteString("filename", file.Filename?.Content ?? "");
                    writer.WriteNumber("kind", (int)file.Kind);
                    if (file.InitScript != null)
                        writer.WriteString("initScript", file.InitScript.Content ?? "");
                    if (file.CleanupScript != null)
                        writer.WriteString("cleanupScript", file.CleanupScript.Content ?? "");

                    writer.WriteStartArray("functions");
                    if (file.Functions != null)
                    {
                        foreach (var func in file.Functions)
                        {
                            writer.WriteStartObject();
                            writer.WriteString("name", func.Name?.Content ?? "");
                            if (func.ExtName != null)
                                writer.WriteString("extName", func.ExtName.Content ?? "");
                            writer.WriteNumber("id", (int)func.ID);
                            writer.WriteNumber("kind", (int)func.Kind);
                            writer.WriteNumber("retType", (int)func.RetType);

                            writer.WriteStartArray("arguments");
                            if (func.Arguments != null)
                            {
                                foreach (var arg in func.Arguments)
                                {
                                    writer.WriteStartObject();
                                    writer.WriteNumber("type", (int)arg.Type);
                                    writer.WriteEndObject();
                                }
                            }
                            writer.WriteEndArray();

                            writer.WriteEndObject();
                        }
                    }
                    writer.WriteEndArray();

                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
            }

            if (extension.Options != null && extension.Options.Count > 0)
            {
                writer.WriteStartArray("options");
                foreach (var option in extension.Options)
                {
                    writer.WriteStartObject();
                    writer.WriteString("name", option.Name?.Content ?? "");
                    writer.WriteString("value", option.Value?.Content ?? "");
                    writer.WriteNumber("kind", (int)option.Kind);
                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
            }

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportExtensions] Failed to export extension {extension.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportExtensions] Export complete. {allExtensions.Count} extensions exported to {extensionsOut}");
