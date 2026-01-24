



using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;




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
    string outputDir = Path.Combine(dataWinDir, "Objects", "Backgrounds");
    Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

string bgOut = ResolveOutputDirectory();
PrintLine($"[ExportBackgrounds] Exporting to: {bgOut}");


List<UndertaleBackground> allBackgrounds;
if (Data.IsGameMaker2())
{
    allBackgrounds = Data.Backgrounds
        .Where(bg => bg.GMS2TileWidth == 0 && bg.GMS2TileHeight == 0)
        .ToList();
}
else
{
    allBackgrounds = Data.Backgrounds.ToList();
}
PrintLine($"[ExportBackgrounds] Found {allBackgrounds.Count} backgrounds to export (excluding tilesets).");

JsonSerializerOptions jsonWriteOptions = new JsonSerializerOptions 
{ 
    WriteIndented = true,
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
};

SetProgressBar(null, "Exporting Backgrounds", 0, allBackgrounds.Count);
StartProgressBarUpdater();

using (TextureWorker worker = new TextureWorker())
{
    await Task.Run(() => Parallel.ForEach(allBackgrounds, bg => ExportBackground(bg, worker, bgOut)));
}

void ExportBackground(UndertaleBackground bg, TextureWorker worker, string outputDir)
{
    if (bg?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(bg.Name.Content);

        
        if (bg.Texture != null)
        {
            string pngPath = Path.Combine(outputDir, name + ".png");
            worker.ExportAsPNG(bg.Texture, pngPath);
        }

        
        var bgMeta = new Dictionary<string, object>
        {
            ["name"] = bg.Name?.Content ?? "",
            ["transparent"] = bg.Transparent,
            ["smooth"] = bg.Smooth,
            ["preload"] = bg.Preload
        };

        
        if (Data.IsGameMaker2())
        {
            bgMeta["gms2UnknownAlways2"] = bg.GMS2UnknownAlways2;
        }

        string metaJson = JsonSerializer.Serialize(bgMeta, jsonWriteOptions);
        string metaFile = Path.Combine(outputDir, name + ".json");
        File.WriteAllText(metaFile, metaJson, Encoding.UTF8);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportBackgrounds] Failed to export background {bg.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportBackgrounds] Export complete. {allBackgrounds.Count} backgrounds exported to {bgOut}");
