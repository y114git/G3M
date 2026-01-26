


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
    string outputDir = Path.Combine(dataWinDir, "Objects", "TextureGroups");
    Directory.CreateDirectory(outputDir);
    return outputDir;
}




EnsureDataLoaded();

if (Data.TextureGroupInfo == null || Data.TextureGroupInfo.Count == 0)
{
    PrintLine("[ExportTextureGroupInfo] No texture group information found in this game. This feature requires GameMaker 2.2.1+ (Bytecode 17+).");
    return;
}

string textureGroupsOut = ResolveOutputDirectory();
PrintLine($"[ExportTextureGroupInfo] Exporting to: {textureGroupsOut}");

List<UndertaleTextureGroupInfo> allTextureGroups = Data.TextureGroupInfo?.ToList() ?? new List<UndertaleTextureGroupInfo>();
PrintLine($"[ExportTextureGroupInfo] Found {allTextureGroups.Count} texture group info entries to export.");

SetProgressBar(null, "Exporting Texture Group Info", 0, allTextureGroups.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allTextureGroups, tg => ExportTextureGroup(tg, textureGroupsOut)));

void ExportTextureGroup(UndertaleTextureGroupInfo textureGroup, string outputDir)
{
    if (textureGroup?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(textureGroup.Name.Content);
        string jsonPath = Path.Combine(outputDir, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            
            writer.WriteString("name", textureGroup.Name.Content);
            
            if (Data.IsVersionAtLeast(2022, 9))
            {
                if (textureGroup.Directory != null)
                    writer.WriteString("directory", textureGroup.Directory.Content ?? "");
                if (textureGroup.Extension != null)
                    writer.WriteString("extension", textureGroup.Extension.Content ?? "");
                writer.WriteNumber("loadType", (int)textureGroup.LoadType);
                writer.WriteString("loadTypeDescription", textureGroup.LoadType.ToString());
            }
            
            writer.WriteStartArray("texturePages");
            if (textureGroup.TexturePages != null)
            {
                foreach (var texPageRef in textureGroup.TexturePages)
                {
                    var texPage = texPageRef.Resource;
                    if (texPage?.Name?.Content != null)
                        writer.WriteStringValue(texPage.Name.Content);
                }
            }
            writer.WriteEndArray();
            
            writer.WriteStartArray("sprites");
            if (textureGroup.Sprites != null)
            {
                foreach (var spriteRef in textureGroup.Sprites)
                {
                    var sprite = spriteRef.Resource;
                    if (sprite?.Name?.Content != null)
                        writer.WriteStringValue(sprite.Name.Content);
                }
            }
            writer.WriteEndArray();
            
            if (!Data.IsNonLTSVersionAtLeast(2023, 1))
            {
                writer.WriteStartArray("spineSprites");
                if (textureGroup.SpineSprites != null)
                {
                    foreach (var spineSpriteRef in textureGroup.SpineSprites)
                    {
                        var spineSprite = spineSpriteRef.Resource;
                        if (spineSprite?.Name?.Content != null)
                            writer.WriteStringValue(spineSprite.Name.Content);
                    }
                }
                writer.WriteEndArray();
            }
            
            writer.WriteStartArray("fonts");
            if (textureGroup.Fonts != null)
            {
                foreach (var fontRef in textureGroup.Fonts)
                {
                    var font = fontRef.Resource;
                    if (font?.Name?.Content != null)
                        writer.WriteStringValue(font.Name.Content);
                }
            }
            writer.WriteEndArray();
            
            writer.WriteStartArray("tilesets");
            if (textureGroup.Tilesets != null)
            {
                foreach (var tilesetRef in textureGroup.Tilesets)
                {
                    var tileset = tilesetRef.Resource;
                    if (tileset?.Name?.Content != null)
                        writer.WriteStringValue(tileset.Name.Content);
                }
            }
            writer.WriteEndArray();
            
            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportTextureGroupInfo] Failed to export texture group info {textureGroup.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportTextureGroupInfo] Export complete. {allTextureGroups.Count} texture group info entries exported to {textureGroupsOut}");
