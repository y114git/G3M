
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

string ReadAllTextSafe(string path)
{
    try { return File.ReadAllText(path).Trim(); } catch { return null; }
}

EnsureDataLoaded();

if (Data.IsYYC())
{
    PrintLine("[ExportTilesets] YYC build detected – tileset export not available.");
    return;
}

string deltahubRoot = null;
{
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
    if (deltahubRoot == null) throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}

string chapterNo = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo     = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

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

