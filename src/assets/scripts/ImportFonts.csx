


using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Collections.Generic;
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

string GetInputDirectory()
{
    string inputDir = Environment.GetEnvironmentVariable("INPUT_DIR");
    if (string.IsNullOrEmpty(inputDir))
        throw new ScriptException("INPUT_DIR environment variable is not set.");
    if (!Directory.Exists(inputDir))
        throw new ScriptException($"INPUT_DIR directory does not exist: {inputDir}");
    return inputDir;
}




EnsureDataLoaded();

string fontsIn = GetInputDirectory();
PrintLine($"[ImportFonts] Importing from: {fontsIn}");

int imported = 0;
int created = 0;
int skipped = 0;


var jsonFiles = Directory.GetFiles(fontsIn, "*.json");
PrintLine($"[ImportFonts] Found {jsonFiles.Length} font JSON file(s) to process");

foreach (string jsonPath in jsonFiles)
{
    string safeName = Path.GetFileNameWithoutExtension(jsonPath);
    string pngPath = Path.Combine(fontsIn, safeName + ".png");
    
    string fontName = safeName;
    try
    {
        string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        if (root.TryGetProperty("name", out JsonElement nameElm))
        {
            fontName = nameElm.GetString() ?? safeName;
        }

        UndertaleFont font = Data.Fonts.ByName(fontName);
        bool isNew = false;

        if (font == null)
        {
            font = new UndertaleFont();
            font.Name = Data.Strings.MakeString(fontName);
            font.DisplayName = Data.Strings.MakeString(fontName);
            font.Glyphs = new UndertalePointerList<UndertaleFont.Glyph>();
            font.EmSize = 12;
            font.Bold = false;
            font.Italic = false;
            font.RangeStart = 32;
            font.RangeEnd = 127;
            font.Charset = 1;
            font.AntiAliasing = 1;
            font.ScaleX = 1.0f;
            font.ScaleY = 1.0f;
            isNew = true;
            created++;
            PrintLine($"[ImportFonts] Creating new font: {fontName}");
        }

        
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
                PrintLine($"[Font] {fontName}: texture imported");
            }
        }

        
        if (root.TryGetProperty("displayName", out JsonElement displayNameElm))
        {
            string displayName = displayNameElm.GetString();
            if (!string.IsNullOrEmpty(displayName))
                font.DisplayName = Data.Strings.MakeString(displayName);
        }

        
        if (root.TryGetProperty("emSize", out JsonElement emSizeElm))
            font.EmSize = (float)emSizeElm.GetDouble();
        if (root.TryGetProperty("emSizeIsFloat", out JsonElement emSizeIsFloatElm))
            font.EmSizeIsFloat = emSizeIsFloatElm.GetBoolean();
        if (root.TryGetProperty("bold", out JsonElement boldElm))
            font.Bold = boldElm.GetBoolean();
        if (root.TryGetProperty("italic", out JsonElement italicElm))
            font.Italic = italicElm.GetBoolean();
        if (root.TryGetProperty("rangeStart", out JsonElement rangeStartElm))
            font.RangeStart = (ushort)rangeStartElm.GetInt32();
        if (root.TryGetProperty("rangeEnd", out JsonElement rangeEndElm))
            font.RangeEnd = (uint)rangeEndElm.GetInt64();
        if (root.TryGetProperty("charset", out JsonElement charsetElm))
            font.Charset = (byte)charsetElm.GetInt32();
        if (root.TryGetProperty("antiAliasing", out JsonElement antiAliasingElm))
            font.AntiAliasing = (byte)antiAliasingElm.GetInt32();
        if (root.TryGetProperty("scaleX", out JsonElement scaleXElm))
            font.ScaleX = (float)scaleXElm.GetDouble();
        if (root.TryGetProperty("scaleY", out JsonElement scaleYElm))
            font.ScaleY = (float)scaleYElm.GetDouble();

        
        if (Data.GeneralInfo?.BytecodeVersion >= 17 && root.TryGetProperty("ascenderOffset", out JsonElement ascenderOffsetElm))
            font.AscenderOffset = ascenderOffsetElm.GetInt32();

        if (Data.IsVersionAtLeast(2022, 2) && root.TryGetProperty("ascender", out JsonElement ascenderElm))
            font.Ascender = (uint)ascenderElm.GetInt64();

        if (Data.IsVersionAtLeast(2023, 2) && root.TryGetProperty("sdfSpread", out JsonElement sdfSpreadElm))
            font.SDFSpread = (uint)sdfSpreadElm.GetInt64();

        if (Data.IsVersionAtLeast(2023, 6) && root.TryGetProperty("lineHeight", out JsonElement lineHeightElm))
            font.LineHeight = (uint)lineHeightElm.GetInt64();

        
        if (root.TryGetProperty("glyphs", out JsonElement glyphsElm) && glyphsElm.ValueKind == JsonValueKind.Array)
        {
            font.Glyphs.Clear();
            foreach (JsonElement glyphElm in glyphsElm.EnumerateArray())
            {
                var glyph = new UndertaleFont.Glyph();

                if (glyphElm.TryGetProperty("character", out JsonElement charElm))
                    glyph.Character = (ushort)charElm.GetInt32();
                if (glyphElm.TryGetProperty("sourceX", out JsonElement sxElm))
                    glyph.SourceX = (ushort)sxElm.GetInt32();
                if (glyphElm.TryGetProperty("sourceY", out JsonElement syElm))
                    glyph.SourceY = (ushort)syElm.GetInt32();
                if (glyphElm.TryGetProperty("sourceWidth", out JsonElement swElm))
                    glyph.SourceWidth = (ushort)swElm.GetInt32();
                if (glyphElm.TryGetProperty("sourceHeight", out JsonElement shElm))
                    glyph.SourceHeight = (ushort)shElm.GetInt32();
                if (glyphElm.TryGetProperty("shift", out JsonElement shiftElm))
                    glyph.Shift = (short)shiftElm.GetInt32();
                if (glyphElm.TryGetProperty("offset", out JsonElement offsetElm))
                    glyph.Offset = (short)offsetElm.GetInt32();

                
                if (glyphElm.TryGetProperty("kerning", out JsonElement kerningElm) && kerningElm.ValueKind == JsonValueKind.Array)
                {
                    glyph.Kerning = new UndertaleSimpleListShort<UndertaleFont.Glyph.GlyphKerning>();
                    foreach (JsonElement kernElm in kerningElm.EnumerateArray())
                    {
                        var kern = new UndertaleFont.Glyph.GlyphKerning();
                        if (kernElm.TryGetProperty("character", out JsonElement kCharElm))
                            kern.Character = (short)kCharElm.GetInt32();
                        if (kernElm.TryGetProperty("shiftModifier", out JsonElement kShiftElm))
                            kern.ShiftModifier = (short)kShiftElm.GetInt32();
                        glyph.Kerning.Add(kern);
                    }
                }

                font.Glyphs.Add(glyph);
            }
        }

        jsonDoc.Dispose();

        if (isNew)
        {
            Data.Fonts.Add(font);
            PrintLine($"[Font] {fontName}: Added to Data.Fonts");
        }

        PrintLine($"[Font] {fontName}: {(isNew ? "CREATED" : "UPDATED")} ({font.Glyphs.Count} glyphs)");
        imported++;
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportFonts] Failed to import {fontName}: {ex.Message}");
        skipped++;
    }
}

PrintLine($"[ImportFonts] Summary: {imported} imported ({created} new), {skipped} skipped");
