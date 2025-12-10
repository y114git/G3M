#load "SharedPaths.csx"

using System;
using System.IO;
using System.Text;
using System.Linq;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;

void PrintLine(string s) => Console.WriteLine(s);



string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

var ctx = PrepareImportContext();
string inputRoot = ctx.InputRoot;
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
        string safeName = SafeName(name);
        string pngPath = Path.Combine(fontsIn, safeName + ".png");
        string csvPath = Path.Combine(fontsIn, $"glyphs_{safeName}.csv");

        if (!File.Exists(pngPath) && !File.Exists(csvPath))
        {
            skipped++;
            continue;
        }

        try
        {
            if (File.Exists(pngPath))
            {
                using (var img = TextureWorker.ReadBGRAImageFromFile(pngPath))
                {
                    
                    
                    int lastTextPage = Data.EmbeddedTextures.Count - 1;
                    int lastTextPageItem = Data.TexturePageItems.Count - 1;

                    UndertaleEmbeddedTexture newEmbeddedTexture = new UndertaleEmbeddedTexture();
                    newEmbeddedTexture.Name = new UndertaleString($"Texture {++lastTextPage}");
                    newEmbeddedTexture.TextureData.Image = GMImage.FromMagickImage(img).ConvertToPng();
                    Data.EmbeddedTextures.Add(newEmbeddedTexture);

                    ushort originalTargetX = font.Texture?.TargetX ?? 0;
                    ushort originalTargetY = font.Texture?.TargetY ?? 0;
                    ushort originalBoundingWidth = font.Texture?.BoundingWidth ?? (ushort)img.Width;
                    ushort originalBoundingHeight = font.Texture?.BoundingHeight ?? (ushort)img.Height;

                    UndertaleTexturePageItem newTexturePageItem = new UndertaleTexturePageItem();
                    newTexturePageItem.Name = new UndertaleString($"PageItem {++lastTextPageItem}");
                    newTexturePageItem.SourceX = 0;
                    newTexturePageItem.SourceY = 0;
                    newTexturePageItem.SourceWidth = (ushort)img.Width;
                    newTexturePageItem.SourceHeight = (ushort)img.Height;
                    newTexturePageItem.TargetX = originalTargetX;
                    newTexturePageItem.TargetY = originalTargetY;
                    newTexturePageItem.TargetWidth = (ushort)img.Width;
                    newTexturePageItem.TargetHeight = (ushort)img.Height;
                    newTexturePageItem.BoundingWidth = originalBoundingWidth;
                    newTexturePageItem.BoundingHeight = originalBoundingHeight;
                    newTexturePageItem.TexturePage = newEmbeddedTexture;
                    Data.TexturePageItems.Add(newTexturePageItem);

                    font.Texture = newTexturePageItem;
                    PrintLine($"[Font] {name}: texture imported");
                }
            }

            if (File.Exists(csvPath))
            {
                font.Glyphs.Clear();
                bool hadError = false;
                using (var reader = new StreamReader(csvPath, Encoding.UTF8))
                {
                    string line;
                    int head = 0;
                    while ((line = reader.ReadLine()) != null)
                    {
                        if (string.IsNullOrWhiteSpace(line)) continue;
                        string[] parts = line.Split(';');
                        if (parts.All(x => x.Length == 0)) continue;

                        try
                        {
                            if (head == 1)
                            {
                                font.RangeStart = UInt16.Parse(parts[0]);
                                head++;
                            }

                            if (head == 0)
                            {
                                String namae = parts[0].Replace("\"", "");
                                font.DisplayName = Data.Strings.MakeString(namae);
                                font.EmSize = UInt16.Parse(parts[1]);
                                font.Bold = Boolean.Parse(parts[2]);
                                font.Italic = Boolean.Parse(parts[3]);
                                font.Charset = Byte.Parse(parts[4]);
                                font.AntiAliasing = Byte.Parse(parts[5]);
                                font.ScaleX = UInt16.Parse(parts[6]);
                                font.ScaleY = UInt16.Parse(parts[7]);
                                head++;
                            }

                            if (head > 1)
                            {
                                font.Glyphs.Add(new UndertaleFont.Glyph()
                                {
                                    Character = UInt16.Parse(parts[0]),
                                    SourceX = UInt16.Parse(parts[1]),
                                    SourceY = UInt16.Parse(parts[2]),
                                    SourceWidth = UInt16.Parse(parts[3]),
                                    SourceHeight = UInt16.Parse(parts[4]),
                                    Shift = Int16.Parse(parts[5]),
                                    Offset = Int16.Parse(parts[6]),
                                });
                                font.RangeEnd = UInt32.Parse(parts[0]);
                            }
                        }
                        catch
                        {
                            hadError = true;
                        }
                    }
                }
                if (hadError)
                {
                    ScriptError($"File \"glyphs_{name}.csv\" contained some invalid data.", "Format error", false);
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
