



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
    string outputDir = Path.Combine(dataWinDir, "Objects", "Tilesets");
    Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

string tilesetOut = ResolveOutputDirectory();
PrintLine($"[ExportTilesets] Exporting to: {tilesetOut}");


List<UndertaleBackground> allTilesets;
if (Data.IsGameMaker2())
{
    allTilesets = Data.Backgrounds
        .Where(bg => bg.GMS2TileWidth > 0 || bg.GMS2TileHeight > 0)
        .ToList();
}
else
{
    
    PrintLine("[ExportTilesets] GMS1 detected - tilesets are handled as backgrounds. Use ExportBackgrounds.csx instead.");
    return;
}

PrintLine($"[ExportTilesets] Found {allTilesets.Count} tilesets to export.");

if (allTilesets.Count == 0)
{
    PrintLine("[ExportTilesets] No tilesets found to export.");
    return;
}

JsonSerializerOptions jsonWriteOptions = new JsonSerializerOptions 
{ 
    WriteIndented = true,
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
};

SetProgressBar(null, "Exporting Tilesets", 0, allTilesets.Count);
StartProgressBarUpdater();

using (TextureWorker worker = new TextureWorker())
{
    await Task.Run(() => Parallel.ForEach(allTilesets, ts => ExportTileset(ts, worker, tilesetOut)));
}

void ExportTileset(UndertaleBackground ts, TextureWorker worker, string outputDir)
{
    if (ts?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(ts.Name.Content);

        
        if (ts.Texture != null)
        {
            string pngPath = Path.Combine(outputDir, name + ".png");
            worker.ExportAsPNG(ts.Texture, pngPath);
        }

        
        var tsMeta = new Dictionary<string, object>
        {
            ["name"] = ts.Name?.Content ?? "",
            ["transparent"] = ts.Transparent,
            ["smooth"] = ts.Smooth,
            ["preload"] = ts.Preload
        };

        
        tsMeta["gms2UnknownAlways2"] = ts.GMS2UnknownAlways2;
        tsMeta["gms2TileWidth"] = ts.GMS2TileWidth;
        tsMeta["gms2TileHeight"] = ts.GMS2TileHeight;
        tsMeta["gms2OutputBorderX"] = ts.GMS2OutputBorderX;
        tsMeta["gms2OutputBorderY"] = ts.GMS2OutputBorderY;
        tsMeta["gms2TileColumns"] = ts.GMS2TileColumns;
        tsMeta["gms2ItemsPerTileCount"] = ts.GMS2ItemsPerTileCount;
        tsMeta["gms2TileCount"] = ts.GMS2TileCount;
        tsMeta["gms2ExportedSpriteIndex"] = ts.GMS2ExportedSpriteIndex;
        tsMeta["gms2FrameLength"] = ts.GMS2FrameLength;

        if (Data.IsVersionAtLeast(2024, 14, 1))
        {
            tsMeta["gms2TileSeparationX"] = ts.GMS2TileSeparationX;
            tsMeta["gms2TileSeparationY"] = ts.GMS2TileSeparationY;
        }

        if (ts.GMS2TileIds != null && ts.GMS2TileIds.Count > 0)
        {
            var tileIds = new List<uint>();
            foreach (var tileId in ts.GMS2TileIds)
                tileIds.Add(tileId.ID);
            tsMeta["gms2TileIds"] = tileIds;
        }

        string metaJson = JsonSerializer.Serialize(tsMeta, jsonWriteOptions);
        string metaFile = Path.Combine(outputDir, name + ".json");
        File.WriteAllText(metaFile, metaJson, Encoding.UTF8);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportTilesets] Failed to export tileset {ts.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportTilesets] Export complete. {allTilesets.Count} tilesets exported to {tilesetOut}");
