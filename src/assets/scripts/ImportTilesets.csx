



using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;




void PrintLine(string s) => Console.WriteLine(s);

string GetInputDirectory()
{
    string inputDir = Environment.GetEnvironmentVariable("INPUT_DIR");
    if (string.IsNullOrEmpty(inputDir))
        throw new ScriptException("INPUT_DIR environment variable is not set.");
    if (!Directory.Exists(inputDir))
        throw new ScriptException($"INPUT_DIR directory does not exist: {inputDir}");
    return inputDir;
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

if (!Data.IsGameMaker2())
{
    PrintLine("[ImportTilesets] GMS1 detected - tilesets are handled as backgrounds. Use ImportBackgrounds.csx instead.");
    return;
}

string tilesetsIn = GetInputDirectory();
PrintLine($"[ImportTilesets] Importing from: {tilesetsIn}");


var tilesetFilesSet = new HashSet<string>();
foreach (var pngFile in Directory.GetFiles(tilesetsIn, "*.png"))
    tilesetFilesSet.Add(Path.GetFileNameWithoutExtension(pngFile));
foreach (var jsonFile in Directory.GetFiles(tilesetsIn, "*.json"))
{
    string name = Path.GetFileNameWithoutExtension(jsonFile);
    if (!name.Equals("config", StringComparison.OrdinalIgnoreCase))
        tilesetFilesSet.Add(name);
}

if (tilesetFilesSet.Count == 0)
{
    PrintLine("[ImportTilesets] No tileset files found - nothing to import.");
    return;
}

PrintLine($"[ImportTilesets] Found {tilesetFilesSet.Count} tileset(s) to process.");

int imported = 0;
int created = 0;

using (TextureWorker worker = new TextureWorker())
{
    foreach (string tsName in tilesetFilesSet)
    {
        string pngPath = Path.Combine(tilesetsIn, tsName + ".png");
        string jsonPath = Path.Combine(tilesetsIn, tsName + ".json");

        if (!File.Exists(pngPath) && !File.Exists(jsonPath))
            continue;

        try
        {
            UndertaleBackground ts = Data.Backgrounds.ByName(tsName);
            bool isNew = false;

            if (ts == null)
            {
                ts = new UndertaleBackground();
                ts.Name = Data.Strings.MakeString(tsName);
                ts.Transparent = false;
                ts.Smooth = false;
                ts.Preload = false;
                isNew = true;
                created++;
                PrintLine($"[ImportTilesets] Creating new tileset: {tsName}");
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

                    ts.Texture = newTexturePageItem;
                }
            }

            
            if (File.Exists(jsonPath))
            {
                string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
                JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
                JsonElement root = jsonDoc.RootElement;

                ts.Transparent = GetJsonValue<bool>(root, "transparent", ts.Transparent);
                ts.Smooth = GetJsonValue<bool>(root, "smooth", ts.Smooth);
                ts.Preload = GetJsonValue<bool>(root, "preload", ts.Preload);

                
                if (root.TryGetProperty("gms2UnknownAlways2", out _))
                    ts.GMS2UnknownAlways2 = GetJsonValue<uint>(root, "gms2UnknownAlways2", ts.GMS2UnknownAlways2);

                ts.GMS2TileWidth = GetJsonValue<uint>(root, "gms2TileWidth", ts.GMS2TileWidth);
                ts.GMS2TileHeight = GetJsonValue<uint>(root, "gms2TileHeight", ts.GMS2TileHeight);
                ts.GMS2OutputBorderX = GetJsonValue<uint>(root, "gms2OutputBorderX", ts.GMS2OutputBorderX);
                ts.GMS2OutputBorderY = GetJsonValue<uint>(root, "gms2OutputBorderY", ts.GMS2OutputBorderY);
                ts.GMS2TileColumns = GetJsonValue<uint>(root, "gms2TileColumns", ts.GMS2TileColumns);
                ts.GMS2ItemsPerTileCount = GetJsonValue<uint>(root, "gms2ItemsPerTileCount", ts.GMS2ItemsPerTileCount);
                ts.GMS2TileCount = GetJsonValue<uint>(root, "gms2TileCount", ts.GMS2TileCount);

                if (root.TryGetProperty("gms2ExportedSpriteIndex", out _))
                    ts.GMS2ExportedSpriteIndex = GetJsonValue<int>(root, "gms2ExportedSpriteIndex", ts.GMS2ExportedSpriteIndex);

                ts.GMS2FrameLength = GetJsonValue<long>(root, "gms2FrameLength", ts.GMS2FrameLength);

                if (Data.IsVersionAtLeast(2024, 14, 1))
                {
                    if (root.TryGetProperty("gms2TileSeparationX", out _))
                        ts.GMS2TileSeparationX = GetJsonValue<uint>(root, "gms2TileSeparationX", ts.GMS2TileSeparationX);
                    if (root.TryGetProperty("gms2TileSeparationY", out _))
                        ts.GMS2TileSeparationY = GetJsonValue<uint>(root, "gms2TileSeparationY", ts.GMS2TileSeparationY);
                }

                if (root.TryGetProperty("gms2TileIds", out JsonElement tileIdsElm) && tileIdsElm.ValueKind == JsonValueKind.Array)
                {
                    int expectedCount = (int)(ts.GMS2TileCount * ts.GMS2ItemsPerTileCount);
                    var tileIdsList = tileIdsElm.EnumerateArray().ToList();
                    
                    if (tileIdsList.Count == expectedCount)
                    {
                        ts.GMS2TileIds.Clear();
                        foreach (var idElm in tileIdsList)
                        {
                            var tileId = new UndertaleBackground.TileID();
                            tileId.ID = (uint)idElm.GetInt64();
                            ts.GMS2TileIds.Add(tileId);
                        }
                    }
                    else if (tileIdsList.Count > 0)
                    {
                        PrintLine($"[ImportTilesets] WARNING: Tile IDs count mismatch for '{tsName}' (expected {expectedCount}, got {tileIdsList.Count}), skipping tile IDs import");
                    }
                }

                jsonDoc.Dispose();
            }

            if (isNew)
            {
                Data.Backgrounds.Add(ts);
            }

            PrintLine($"[ImportTilesets] {(isNew ? "Created" : "Updated")} tileset: {tsName}");
            imported++;
        }
        catch (Exception ex)
        {
            PrintLine($"[ImportTilesets] Failed to import {tsName}: {ex.Message}");
        }
    }
}

PrintLine($"[ImportTilesets] Import complete. {imported} tilesets processed ({created} new).");
