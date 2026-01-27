


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

string fontsOut = GetOutputDirectory();
PrintLine($"[ExportFonts] Exporting to: {fontsOut}");

List<UndertaleFont> allFonts = Data.Fonts.ToList();
PrintLine($"[ExportFonts] Found {allFonts.Count} fonts to export.");

SetProgressBar(null, "Exporting Fonts", 0, allFonts.Count);
StartProgressBarUpdater();

using (TextureWorker worker = new TextureWorker())
{
    await Task.Run(() => Parallel.ForEach(allFonts, font => ExportFont(font, worker, fontsOut)));
}

void ExportFont(UndertaleFont font, TextureWorker worker, string outputDir)
{
    if (font?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(font.Name.Content);

        
        if (font.Texture != null)
        {
            string pngPath = Path.Combine(outputDir, name + ".png");
            worker.ExportAsPNG(font.Texture, pngPath);
        }

        
        using (var stream = new FileStream(Path.Combine(outputDir, name + ".json"), FileMode.Create))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();

            
            writer.WriteString("name", font.Name?.Content ?? "");
            writer.WriteString("displayName", font.DisplayName?.Content ?? "");
            writer.WriteNumber("emSize", font.EmSize);
            writer.WriteBoolean("bold", font.Bold);
            writer.WriteBoolean("italic", font.Italic);
            writer.WriteNumber("rangeStart", font.RangeStart);
            writer.WriteNumber("rangeEnd", font.RangeEnd);
            writer.WriteNumber("charset", font.Charset);
            writer.WriteNumber("antiAliasing", font.AntiAliasing);
            writer.WriteNumber("scaleX", font.ScaleX);
            writer.WriteNumber("scaleY", font.ScaleY);

            
            writer.WriteBoolean("emSizeIsFloat", font.EmSizeIsFloat);

            if (Data.GeneralInfo?.BytecodeVersion >= 17)
                writer.WriteNumber("ascenderOffset", font.AscenderOffset);

            if (Data.IsVersionAtLeast(2022, 2))
                writer.WriteNumber("ascender", font.Ascender);

            if (Data.IsVersionAtLeast(2023, 2))
                writer.WriteNumber("sdfSpread", font.SDFSpread);

            if (Data.IsVersionAtLeast(2023, 6))
                writer.WriteNumber("lineHeight", font.LineHeight);

            
            writer.WritePropertyName("glyphs");
            writer.WriteStartArray();
            foreach (var g in font.Glyphs)
            {
                writer.WriteStartObject();
                writer.WriteNumber("character", g.Character);
                writer.WriteNumber("sourceX", g.SourceX);
                writer.WriteNumber("sourceY", g.SourceY);
                writer.WriteNumber("sourceWidth", g.SourceWidth);
                writer.WriteNumber("sourceHeight", g.SourceHeight);
                writer.WriteNumber("shift", g.Shift);
                writer.WriteNumber("offset", g.Offset);

                
                if (g.Kerning != null && g.Kerning.Count > 0)
                {
                    writer.WritePropertyName("kerning");
                    writer.WriteStartArray();
                    foreach (var k in g.Kerning)
                    {
                        writer.WriteStartObject();
                        writer.WriteNumber("character", k.Character);
                        writer.WriteNumber("shiftModifier", k.ShiftModifier);
                        writer.WriteEndObject();
                    }
                    writer.WriteEndArray();
                }

                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportFonts] Failed to export font {font.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportFonts] Export complete. {allFonts.Count} fonts exported to {fontsOut}");
