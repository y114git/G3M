


using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;




string InputDirectory = "";




void PrintLine(string s) => Console.WriteLine(s);

string ResolveInputDirectory()
{
    if (!string.IsNullOrEmpty(InputDirectory) && Directory.Exists(InputDirectory))
        return InputDirectory;

    if (string.IsNullOrEmpty(FilePath))
        throw new ScriptException("No data.win file loaded. Please load a game data file first.");

    string dataWinDir = Path.GetDirectoryName(FilePath);
    string textureGroupsDir = Path.Combine(dataWinDir, "Objects", "TextureGroups");
    
    if (Directory.Exists(textureGroupsDir))
        return textureGroupsDir;

    throw new ScriptException($"TextureGroups directory not found at: {textureGroupsDir}\nPlease specify InputDirectory or place texture groups in an 'Objects/TextureGroups' folder next to data.win.");
}




EnsureDataLoaded();

if (Data.TextureGroupInfo == null)
{
    PrintLine("[ImportTextureGroupInfo] This game does not support texture group information. This feature requires GameMaker 2.2.1+ (Bytecode 17+).");
    return;
}

string textureGroupsDir = ResolveInputDirectory();
PrintLine($"[ImportTextureGroupInfo] Importing from: {textureGroupsDir}");

string[] textureGroupFiles = Directory.GetFiles(textureGroupsDir, "*.json");
if (textureGroupFiles.Length == 0)
{
    PrintLine("[ImportTextureGroupInfo] No texture group info JSON files found, skipping import.");
    return;
}

PrintLine($"[ImportTextureGroupInfo] Found {textureGroupFiles.Length} texture group info file(s) to import.");

SetProgressBar(null, "Importing Texture Group Info", 0, textureGroupFiles.Length);
StartProgressBarUpdater();

foreach (string textureGroupFile in textureGroupFiles)
{
    try
    {
        string jsonContent = File.ReadAllText(textureGroupFile, Encoding.UTF8);
        string textureGroupName = Path.GetFileNameWithoutExtension(textureGroupFile);
        
        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;
        
        UndertaleTextureGroupInfo textureGroup = Data.TextureGroupInfo.FirstOrDefault(tg => tg.Name?.Content == textureGroupName);
        if (textureGroup == null)
        {
            textureGroup = new UndertaleTextureGroupInfo();
            textureGroup.Name = Data.Strings.MakeString(textureGroupName);
            Data.TextureGroupInfo.Add(textureGroup);
            PrintLine($"[ImportTextureGroupInfo] Created new texture group info: {textureGroupName}");
        }
        else
        {
            PrintLine($"[ImportTextureGroupInfo] Updating existing texture group info: {textureGroupName}");
        }
        
        UpdateTextureGroupFromJson(textureGroup, root);
        
        jsonDoc.Dispose();
        IncrementProgress();
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportTextureGroupInfo] Error importing texture group info {Path.GetFileName(textureGroupFile)}: {ex.Message}");
    }
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine("[ImportTextureGroupInfo] Texture group info import completed.");

void UpdateTextureGroupFromJson(UndertaleTextureGroupInfo textureGroup, JsonElement data)
{
    if (data.TryGetProperty("name", out JsonElement nameElm) && nameElm.ValueKind == JsonValueKind.String)
        textureGroup.Name = Data.Strings.MakeString(nameElm.GetString());
    
    if (Data.IsVersionAtLeast(2022, 9))
    {
        if (data.TryGetProperty("directory", out JsonElement dirElm) && dirElm.ValueKind == JsonValueKind.String)
            textureGroup.Directory = Data.Strings.MakeString(dirElm.GetString());
        
        if (data.TryGetProperty("extension", out JsonElement extElm) && extElm.ValueKind == JsonValueKind.String)
            textureGroup.Extension = Data.Strings.MakeString(extElm.GetString());
        
        if (data.TryGetProperty("loadType", out JsonElement loadTypeElm) && loadTypeElm.ValueKind == JsonValueKind.Number)
            textureGroup.LoadType = (UndertaleTextureGroupInfo.TextureGroupLoadType)loadTypeElm.GetInt32();
    }
    
    if (data.TryGetProperty("texturePages", out JsonElement texPagesElm) && texPagesElm.ValueKind == JsonValueKind.Array)
    {
        textureGroup.TexturePages.Clear();
        foreach (JsonElement texPageElm in texPagesElm.EnumerateArray())
        {
            if (texPageElm.ValueKind == JsonValueKind.String)
            {
                string texPageName = texPageElm.GetString();
                if (!string.IsNullOrEmpty(texPageName))
                {
                    var texPage = Data.EmbeddedTextures.FirstOrDefault(t => t.Name?.Content == texPageName);
                    if (texPage != null)
                        textureGroup.TexturePages.Add(texPage);
                    else
                        PrintLine($"[ImportTextureGroupInfo] Warning: Texture page '{texPageName}' not found in game data.");
                }
            }
        }
    }
    
    if (data.TryGetProperty("sprites", out JsonElement spritesElm) && spritesElm.ValueKind == JsonValueKind.Array)
    {
        textureGroup.Sprites.Clear();
        foreach (JsonElement spriteElm in spritesElm.EnumerateArray())
        {
            if (spriteElm.ValueKind == JsonValueKind.String)
            {
                string spriteName = spriteElm.GetString();
                if (!string.IsNullOrEmpty(spriteName))
                {
                    var sprite = Data.Sprites.ByName(spriteName);
                    if (sprite != null)
                        textureGroup.Sprites.Add(sprite);
                    else
                        PrintLine($"[ImportTextureGroupInfo] Warning: Sprite '{spriteName}' not found in game data.");
                }
            }
        }
    }
    
    if (!Data.IsNonLTSVersionAtLeast(2023, 1))
    {
        if (data.TryGetProperty("spineSprites", out JsonElement spineSpritesElm) && spineSpritesElm.ValueKind == JsonValueKind.Array)
        {
            textureGroup.SpineSprites.Clear();
            foreach (JsonElement spineSpriteElm in spineSpritesElm.EnumerateArray())
            {
                if (spineSpriteElm.ValueKind == JsonValueKind.String)
                {
                    string spineSpriteName = spineSpriteElm.GetString();
                    if (!string.IsNullOrEmpty(spineSpriteName))
                    {
                        var spineSprite = Data.Sprites.ByName(spineSpriteName);
                        if (spineSprite != null)
                            textureGroup.SpineSprites.Add(spineSprite);
                        else
                            PrintLine($"[ImportTextureGroupInfo] Warning: Spine sprite '{spineSpriteName}' not found in game data.");
                    }
                }
            }
        }
    }
    
    if (data.TryGetProperty("fonts", out JsonElement fontsElm) && fontsElm.ValueKind == JsonValueKind.Array)
    {
        textureGroup.Fonts.Clear();
        foreach (JsonElement fontElm in fontsElm.EnumerateArray())
        {
            if (fontElm.ValueKind == JsonValueKind.String)
            {
                string fontName = fontElm.GetString();
                if (!string.IsNullOrEmpty(fontName))
                {
                    var font = Data.Fonts.ByName(fontName);
                    if (font != null)
                        textureGroup.Fonts.Add(font);
                    else
                        PrintLine($"[ImportTextureGroupInfo] Warning: Font '{fontName}' not found in game data.");
                }
            }
        }
    }
    
    if (data.TryGetProperty("tilesets", out JsonElement tilesetsElm) && tilesetsElm.ValueKind == JsonValueKind.Array)
    {
        textureGroup.Tilesets.Clear();
        foreach (JsonElement tilesetElm in tilesetsElm.EnumerateArray())
        {
            if (tilesetElm.ValueKind == JsonValueKind.String)
            {
                string tilesetName = tilesetElm.GetString();
                if (!string.IsNullOrEmpty(tilesetName))
                {
                    var tileset = Data.Backgrounds.ByName(tilesetName);
                    if (tileset != null)
                        textureGroup.Tilesets.Add(tileset);
                    else
                        PrintLine($"[ImportTextureGroupInfo] Warning: Tileset '{tilesetName}' not found in game data.");
                }
            }
        }
    }
}
