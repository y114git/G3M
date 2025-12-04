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
    PrintLine("[ExportFonts] YYC build detected – font export not available.");
    return;
}

string deltahubRoot = FindDeltahubRoot();
string chapterNo = GetChapterNumber(deltahubRoot);
string modNo = GetModNumbersCache(deltahubRoot);
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

string comparisonPath = null;
if (modNo != "0" && modNo != "1")
{
    int modNum = int.Parse(modNo);
    string previousModPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, (modNum - 1).ToString(), "data.win");
    if (File.Exists(previousModPath))
    {
        comparisonPath = previousModPath;
    }
}
if (comparisonPath == null)
{
    comparisonPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, "0", "data.win");
}

string modRoot         = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string outputRoot      = Path.Combine(modRoot, "Objects");
string fontsOut        = Path.Combine(outputRoot, "Fonts");

Directory.CreateDirectory(outputRoot);
Directory.CreateDirectory(fontsOut);

UndertaleData comparison = null;
Dictionary<string, UndertaleFont> comparisonFonts = new Dictionary<string, UndertaleFont>();
if (File.Exists(comparisonPath))
{
    PrintLine($"[ExportFonts] Loading comparison file from: {comparisonPath}");
    using (var fs = new FileStream(comparisonPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        comparison = UndertaleIO.Read(fs);
    if (comparison != null)
    {
        foreach (var font in comparison.Fonts)
        {
            if (font?.Name?.Content != null)
                comparisonFonts[font.Name.Content] = font;
        }
    }
}

int exported = 0;
int skipped = 0;

using (var worker = new TextureWorker())
{
    foreach (var font in Data.Fonts)
    {
        if (font?.Name?.Content == null) continue;
        string name = SafeName(font.Name.Content);
        
        bool shouldExport = false;
        if (!comparisonFonts.ContainsKey(font.Name.Content))
        {
            shouldExport = true;
            PrintLine($"[Font] {name}: NEW (not in comparison)");
        }
        else
        {
            var compFont = comparisonFonts[font.Name.Content];
            if (font.Texture?.TexturePage?.Name?.Content != compFont.Texture?.TexturePage?.Name?.Content ||
                font.DisplayName?.Content != compFont.DisplayName?.Content ||
                font.EmSize != compFont.EmSize ||
                font.Bold != compFont.Bold ||
                font.Italic != compFont.Italic ||
                font.Charset != compFont.Charset ||
                font.AntiAliasing != compFont.AntiAliasing ||
                font.ScaleX != compFont.ScaleX ||
                font.ScaleY != compFont.ScaleY ||
                font.Glyphs.Count != compFont.Glyphs.Count)
            {
                shouldExport = true;
                PrintLine($"[Font] {name}: MODIFIED");
            }
            else
            {
                bool glyphsDiffer = false;
                for (int i = 0; i < font.Glyphs.Count && i < compFont.Glyphs.Count; i++)
                {
                    var g = font.Glyphs[i];
                    var cg = compFont.Glyphs[i];
                    if (g.Character != cg.Character ||
                        g.SourceX != cg.SourceX ||
                        g.SourceY != cg.SourceY ||
                        g.SourceWidth != cg.SourceWidth ||
                        g.SourceHeight != cg.SourceHeight ||
                        g.Shift != cg.Shift ||
                        g.Offset != cg.Offset)
                    {
                        glyphsDiffer = true;
                        break;
                    }
                }
                if (glyphsDiffer)
                {
                    shouldExport = true;
                    PrintLine($"[Font] {name}: MODIFIED (glyphs differ)");
                }
                else
                {
                    DebugLog($"[ExportFonts] Skipping {name}: unchanged");
                    skipped++;
                    continue;
                }
            }
        }
        
        if (!shouldExport) continue;
        
        try
        {
            if (font.Texture?.TexturePage?.Texture != null)
            {
                string png = Path.Combine(fontsOut, name + ".png");
                worker.ExportAsPNG(font.Texture.TexturePage.Texture, png);
            }
            
            string csv = Path.Combine(fontsOut, $"glyphs_{name}.csv");
            using (var writer = new StreamWriter(csv, false, Encoding.UTF8))
            {
                writer.WriteLine($"{font.DisplayName?.Content ?? ""};{font.EmSize};{font.Bold};{font.Italic};{font.Charset};{font.AntiAliasing};{font.ScaleX};{font.ScaleY}");
                
                foreach (var g in font.Glyphs)
                {
                    writer.WriteLine($"{g.Character};{g.SourceX};{g.SourceY};{g.SourceWidth};{g.SourceHeight};{g.Shift};{g.Offset}");
                }
            }
            
            PrintLine($"[Font] {name}: EXPORTED");
            exported++;
        }
        catch (Exception ex)
        {
            PrintLine($"[ExportFonts] Failed to export {name}: {ex.Message}");
            skipped++;
        }
    }
}

PrintLine($"[ExportFonts] Summary: {exported} exported, {skipped} skipped");

