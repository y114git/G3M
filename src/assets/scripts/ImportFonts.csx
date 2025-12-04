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

byte[] ReadAllBytesSafe(string path)
{
    try { return File.ReadAllBytes(path); } catch { return null; }
}

EnsureDataLoaded();

string deltahubRoot = FindDeltahubRoot();
string chapterNo = GetChapterNumber(deltahubRoot);
string modNo = GetModNumbersCache(deltahubRoot);

string inputRoot = null;
if (!string.IsNullOrEmpty(FilePath))
{
    string dataWinDir = Path.GetDirectoryName(FilePath);
    string objectsNextToDataWin = Path.Combine(dataWinDir, "Objects");
    if (Directory.Exists(objectsNextToDataWin))
    {
        inputRoot = objectsNextToDataWin;
        Console.WriteLine($"[ImportFonts] Using Objects directory next to data.win: {inputRoot}");
    }
}

if (inputRoot == null)
{
    if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

    string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
    inputRoot = Path.Combine(modRoot, "Objects");
    Console.WriteLine($"[ImportFonts] Using Objects directory from modNumbersCache: {inputRoot}");
}

string fontsIn = Path.Combine(inputRoot, "Fonts");

if (!Directory.Exists(fontsIn))
{
    PrintLine("[ImportFonts] No Fonts directory found, skipping.");
    return;
}

int imported = 0;
int skipped = 0;

using (var worker = new TextureWorker())
{
    foreach (var font in Data.Fonts)
    {
        if (font?.Name?.Content == null) continue;
        string name = font.Name.Content;
        
        string pngPath = Path.Combine(fontsIn, name + ".png");
        string csvPath = Path.Combine(fontsIn, $"glyphs_{name}.csv");
        
        if (!File.Exists(pngPath) && !File.Exists(csvPath))
        {
            DebugLog($"[ImportFonts] Skipping {name}: no files found");
            skipped++;
            continue;
        }
        
        try
        {
            if (File.Exists(pngPath))
            {
                using (var img = TextureWorker.ReadBGRAImageFromFile(pngPath))
                {
                    if (font.Texture?.TexturePage?.Texture != null)
                    {
                        font.Texture.TexturePage.Texture.ReplaceTexture(img);
                        PrintLine($"[Font] {name}: texture imported");
                    }
                }
            }
            
            if (File.Exists(csvPath))
            {
                font.Glyphs.Clear();
                using (var reader = new StreamReader(csvPath, Encoding.UTF8))
                {
                    string line;
                    int head = 0;
                    while ((line = reader.ReadLine()) != null)
                    {
                        if (string.IsNullOrWhiteSpace(line)) continue;
                        
                        string[] parts = line.Split(';');
                        if (parts.Length < 8) continue;
                        
                        if (head == 0)
                        {
                            string displayName = parts[0].Replace("\"", "");
                            font.DisplayName = Data.Strings.MakeString(displayName);
                            font.EmSize = ushort.Parse(parts[1]);
                            font.Bold = bool.Parse(parts[2]);
                            font.Italic = bool.Parse(parts[3]);
                            font.Charset = byte.Parse(parts[4]);
                            font.AntiAliasing = byte.Parse(parts[5]);
                            font.ScaleX = ushort.Parse(parts[6]);
                            font.ScaleY = ushort.Parse(parts[7]);
                            head++;
                        }
                        else if (head == 1)
                        {
                            font.RangeStart = ushort.Parse(parts[0]);
                            head++;
                        }
                        else if (head > 1 && parts.Length >= 7)
                        {
                            var glyph = new UndertaleFont.Glyph
                            {
                                Character = ushort.Parse(parts[0]),
                                SourceX = ushort.Parse(parts[1]),
                                SourceY = ushort.Parse(parts[2]),
                                SourceWidth = ushort.Parse(parts[3]),
                                SourceHeight = ushort.Parse(parts[4]),
                                Shift = short.Parse(parts[5]),
                                Offset = short.Parse(parts[6])
                            };
                            font.Glyphs.Add(glyph);
                            font.RangeEnd = uint.Parse(parts[0]);
                        }
                    }
                }
                PrintLine($"[Font] {name}: glyphs imported ({font.Glyphs.Count} glyphs)");
            }
            
            PrintLine($"[Font] {name}: IMPORTED");
            imported++;
        }
        catch (Exception ex)
        {
            PrintLine($"[ImportFonts] Failed to import {name}: {ex.Message}");
            skipped++;
        }
    }
}

PrintLine($"[ImportFonts] Summary: {imported} imported, {skipped} skipped");

