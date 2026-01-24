



using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;




string InputDirectory = "";




void PrintLine(string s) => Console.WriteLine(s);

string ResolveInputDirectory()
{
    if (!string.IsNullOrEmpty(InputDirectory) && Directory.Exists(InputDirectory))
        return InputDirectory;

    if (string.IsNullOrEmpty(FilePath))
        throw new ScriptException("No data.win file loaded. Please load a game data file first.");

    string dataWinDir = Path.GetDirectoryName(FilePath);
    string bgDir = Path.Combine(dataWinDir, "Objects", "Backgrounds");
    
    if (Directory.Exists(bgDir))
        return bgDir;

    throw new ScriptException($"Backgrounds directory not found at: {bgDir}\nPlease specify InputDirectory or place backgrounds in an 'Objects/Backgrounds' folder next to data.win.");
}

T GetJsonValue<T>(JsonElement root, string propertyName, T defaultValue)
{
    if (root.TryGetProperty(propertyName, out JsonElement elm))
    {
        try
        {
            if (typeof(T) == typeof(uint))
                return (T)(object)(uint)elm.GetInt64();
            if (typeof(T) == typeof(int))
                return (T)(object)elm.GetInt32();
            if (typeof(T) == typeof(long))
                return (T)(object)elm.GetInt64();
            if (typeof(T) == typeof(bool))
                return (T)(object)elm.GetBoolean();
            if (typeof(T) == typeof(float))
                return (T)(object)(float)elm.GetDouble();
            if (typeof(T) == typeof(string))
                return (T)(object)(elm.GetString() ?? "");
        }
        catch { }
    }
    return defaultValue;
}




EnsureDataLoaded();

string bgDir = ResolveInputDirectory();
PrintLine($"[ImportBackgrounds] Importing from: {bgDir}");


var bgFilesSet = new HashSet<string>();
foreach (var pngFile in Directory.GetFiles(bgDir, "*.png"))
    bgFilesSet.Add(Path.GetFileNameWithoutExtension(pngFile));
foreach (var jsonFile in Directory.GetFiles(bgDir, "*.json"))
    bgFilesSet.Add(Path.GetFileNameWithoutExtension(jsonFile));

if (bgFilesSet.Count == 0)
{
    PrintLine("[ImportBackgrounds] No background files found - nothing to import.");
    return;
}

PrintLine($"[ImportBackgrounds] Found {bgFilesSet.Count} background(s) to process.");

int imported = 0;
int created = 0;

using (TextureWorker worker = new TextureWorker())
{
    foreach (string bgName in bgFilesSet)
    {
        string pngPath = Path.Combine(bgDir, bgName + ".png");
        string jsonPath = Path.Combine(bgDir, bgName + ".json");

        if (!File.Exists(pngPath) && !File.Exists(jsonPath))
            continue;

        try
        {
            UndertaleBackground bg = Data.Backgrounds.ByName(bgName);
            bool isNew = false;

            if (bg == null)
            {
                bg = new UndertaleBackground();
                bg.Name = Data.Strings.MakeString(bgName);
                bg.Transparent = false;
                bg.Smooth = false;
                bg.Preload = false;
                isNew = true;
                created++;
                PrintLine($"[ImportBackgrounds] Creating new background: {bgName}");
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

                    UndertaleTexturePageItem newTexturePageItem = new UndertaleTexturePageItem();
                    newTexturePageItem.Name = new UndertaleString($"PageItem {++lastTextPageItem}");
                    newTexturePageItem.SourceX = 0;
                    newTexturePageItem.SourceY = 0;
                    newTexturePageItem.SourceWidth = (ushort)img.Width;
                    newTexturePageItem.SourceHeight = (ushort)img.Height;
                    newTexturePageItem.TargetX = 0;
                    newTexturePageItem.TargetY = 0;
                    newTexturePageItem.TargetWidth = (ushort)img.Width;
                    newTexturePageItem.TargetHeight = (ushort)img.Height;
                    newTexturePageItem.BoundingWidth = (ushort)img.Width;
                    newTexturePageItem.BoundingHeight = (ushort)img.Height;
                    newTexturePageItem.TexturePage = newEmbeddedTexture;
                    Data.TexturePageItems.Add(newTexturePageItem);

                    bg.Texture = newTexturePageItem;
                }
            }

            
            if (File.Exists(jsonPath))
            {
                string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
                JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
                JsonElement root = jsonDoc.RootElement;

                bg.Transparent = GetJsonValue<bool>(root, "transparent", bg.Transparent);
                bg.Smooth = GetJsonValue<bool>(root, "smooth", bg.Smooth);
                bg.Preload = GetJsonValue<bool>(root, "preload", bg.Preload);

                
                if (Data.IsGameMaker2())
                {
                    if (root.TryGetProperty("gms2UnknownAlways2", out _))
                        bg.GMS2UnknownAlways2 = GetJsonValue<uint>(root, "gms2UnknownAlways2", bg.GMS2UnknownAlways2);
                }

                jsonDoc.Dispose();
            }

            if (isNew)
            {
                Data.Backgrounds.Add(bg);
            }

            PrintLine($"[ImportBackgrounds] {(isNew ? "Created" : "Updated")} background: {bgName}");
            imported++;
        }
        catch (Exception ex)
        {
            PrintLine($"[ImportBackgrounds] Failed to import {bgName}: {ex.Message}");
        }
    }
}

PrintLine($"[ImportBackgrounds] Import complete. {imported} backgrounds processed ({created} new).");
