#load "SharedPaths.csx"

using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

EnsureDataLoaded();

if (Data.IsYYC())
{
    PrintLine("[ExportTilesets] YYC build detected – tileset export not available.");
    return;
}

string deltahubRoot = FindDeltahubRoot();
string chapterNo = GetChapterNumber(deltahubRoot);
string modNo = GetModNumbersCache(deltahubRoot);
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");


UndertaleData vanillaData = LoadVanillaData();
Dictionary<string, UndertaleBackground> vanillaTilesets = new Dictionary<string, UndertaleBackground>();
if (vanillaData != null)
{
    foreach(var bg in vanillaData.Backgrounds)
        if (bg.Name?.Content != null) vanillaTilesets[bg.Name.Content] = bg;
}

string outputRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string backgroundsOut = Path.Combine(outputRoot, "Objects", "Backgrounds"); 
Directory.CreateDirectory(backgroundsOut);

PrintLine($"[ExportTilesets] Exporting tilesets to: {backgroundsOut}");

int exported = 0;
int skipped = 0;

using (var worker = new TextureWorker())
{
    foreach (var bg in Data.Backgrounds)
    {
        if (bg?.Name?.Content == null) continue;
        
        
        
        string name = SafeName(bg.Name.Content);

        bool isChanged = true;
        if (vanillaData != null && vanillaTilesets.ContainsKey(bg.Name.Content))
        {
            var vBg = vanillaTilesets[bg.Name.Content];
            
            bool propsChanged = bg.TileWidth != vBg.TileWidth || bg.TileHeight != vBg.TileHeight ||
                                bg.TileXOffset != vBg.TileXOffset || bg.TileYOffset != vBg.TileYOffset ||
                                bg.TileXSep != vBg.TileXSep || bg.TileYSep != vBg.TileYSep;
            
            
            bool texChanged = false;
            if (bg.Texture != null && vBg.Texture != null)
            {
                 if (bg.Texture.SourceX != vBg.Texture.SourceX || bg.Texture.SourceY != vBg.Texture.SourceY ||
                     bg.Texture.SourceWidth != vBg.Texture.SourceWidth || bg.Texture.SourceHeight != vBg.Texture.SourceHeight ||
                     bg.Texture.TexturePage?.Name?.Content != vBg.Texture.TexturePage?.Name?.Content)
                 {
                     texChanged = true;
                 }
            }
            else if (bg.Texture != vBg.Texture) texChanged = true; 

            if (!propsChanged && !texChanged) isChanged = false;
        }

        if (!isChanged) 
        {
            LogSkip("Tileset", name);
            skipped++;
            continue;
        }
        
        if (bg?.Texture == null)
        {
            DebugLog($"[ExportTilesets] Skipping {name}: no texture");
            skipped++;
            continue;
        }
        
        try
        {
            string png = Path.Combine(backgroundsOut, name + ".png");
            worker.ExportAsPNG(bg.Texture, png);
            PrintLine($"[Tileset] {name}: EXPORTED");
            exported++;
        }
        catch (Exception ex)
        {
            PrintLine($"[ExportTilesets] Failed to export {name}: {ex.Message}");
            skipped++;
        }
    }
}

PrintLine($"[ExportTilesets] Summary: {exported} exported, {skipped} skipped");

