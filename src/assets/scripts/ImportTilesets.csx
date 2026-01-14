#load "SharedPaths.csx"

using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;

void PrintLine(string s) => Console.WriteLine(s);

var ctx = PrepareImportContext();
string inputRoot = ctx.InputRoot;
string tilesetsIn = Path.Combine(inputRoot, "Tilesets");

if (!Directory.Exists(tilesetsIn))
{
    PrintLine("[ImportTilesets] No Tilesets directory found, skipping.");
    return;
}

int tilesetsImported = 0;


T GetJsonValue<T>(JsonElement root, string camelCaseName, string snakeCaseName, T defaultValue)
{
    
    if (root.TryGetProperty(camelCaseName, out JsonElement elm))
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

    
    if (!string.IsNullOrEmpty(snakeCaseName) && root.TryGetProperty(snakeCaseName, out JsonElement snakeElm))
    {
        try
        {
            if (typeof(T) == typeof(uint))
                return (T)(object)(uint)snakeElm.GetInt64();
            if (typeof(T) == typeof(int))
                return (T)(object)snakeElm.GetInt32();
            if (typeof(T) == typeof(long))
                return (T)(object)snakeElm.GetInt64();
            if (typeof(T) == typeof(bool))
                return (T)(object)snakeElm.GetBoolean();
            if (typeof(T) == typeof(float))
                return (T)(object)(float)snakeElm.GetDouble();
            if (typeof(T) == typeof(string))
                return (T)(object)(snakeElm.GetString() ?? "");
        }
        catch { }
    }

    return defaultValue;
}

void ImportTilesetFromJson(string jsonPath)
{
    try
    {
        string jsonContent = File.ReadAllText(jsonPath, Encoding.UTF8);
        if (string.IsNullOrEmpty(jsonContent))
        {
            PrintLine($"[ImportTilesets] ERROR: Failed to read {jsonPath}");
            return;
        }

        string tilesetName = Path.GetFileNameWithoutExtension(jsonPath);
        UndertaleBackground bg = Data.Backgrounds.ByName(tilesetName);

        if (bg == null)
        {
            PrintLine($"[ImportTilesets] WARNING: Background '{tilesetName}' not found, skipping properties import");
            return;
        }

        JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
        JsonElement root = jsonDoc.RootElement;

        
        bg.Transparent = GetJsonValue<bool>(root, "transparent", "transparent", bg.Transparent);
        bg.Smooth = GetJsonValue<bool>(root, "smooth", "smooth", bg.Smooth);
        bg.Preload = GetJsonValue<bool>(root, "preload", "preload", bg.Preload);

        
        if (Data.IsGameMaker2())
        {
            
            if (root.TryGetProperty("gms2UnknownAlways2", out _))
            {
                bg.GMS2UnknownAlways2 = GetJsonValue<uint>(root, "gms2UnknownAlways2", null, bg.GMS2UnknownAlways2);
            }

            
            bg.GMS2TileWidth = GetJsonValue<uint>(root, "gms2TileWidth", "tile_width", bg.GMS2TileWidth);
            bg.GMS2TileHeight = GetJsonValue<uint>(root, "gms2TileHeight", "tile_height", bg.GMS2TileHeight);

            
            bg.GMS2OutputBorderX = GetJsonValue<uint>(root, "gms2OutputBorderX", "border_x", bg.GMS2OutputBorderX);
            bg.GMS2OutputBorderY = GetJsonValue<uint>(root, "gms2OutputBorderY", "border_y", bg.GMS2OutputBorderY);

            
            bg.GMS2TileColumns = GetJsonValue<uint>(root, "gms2TileColumns", "tile_column", bg.GMS2TileColumns);
            bg.GMS2ItemsPerTileCount = GetJsonValue<uint>(root, "gms2ItemsPerTileCount", "item_per_tile", bg.GMS2ItemsPerTileCount);
            bg.GMS2TileCount = GetJsonValue<uint>(root, "gms2TileCount", "tile_count", bg.GMS2TileCount);

            
            if (root.TryGetProperty("gms2ExportedSpriteIndex", out _))
            {
                bg.GMS2ExportedSpriteIndex = GetJsonValue<int>(root, "gms2ExportedSpriteIndex", null, bg.GMS2ExportedSpriteIndex);
            }

            
            bg.GMS2FrameLength = GetJsonValue<long>(root, "gms2FrameLength", "frametime", bg.GMS2FrameLength);

            
            if (Data.IsVersionAtLeast(2024, 14, 1))
            {
                if (root.TryGetProperty("gms2TileSeparationX", out _))
                {
                    bg.GMS2TileSeparationX = GetJsonValue<uint>(root, "gms2TileSeparationX", null, bg.GMS2TileSeparationX);
                }
                if (root.TryGetProperty("gms2TileSeparationY", out _))
                {
                    bg.GMS2TileSeparationY = GetJsonValue<uint>(root, "gms2TileSeparationY", null, bg.GMS2TileSeparationY);
                }
            }

            
            if (root.TryGetProperty("gms2TileIds", out JsonElement tileIdsElm) && tileIdsElm.ValueKind == JsonValueKind.Array)
            {
                int expectedCount = (int)(bg.GMS2TileCount * bg.GMS2ItemsPerTileCount);
                var tileIdsList = tileIdsElm.EnumerateArray().ToList();
                
                
                if (tileIdsList.Count == expectedCount)
                {
                    bg.GMS2TileIds.Clear();
                    foreach (var idElm in tileIdsList)
                    {
                        var tileId = new UndertaleBackground.TileID();
                        tileId.ID = (uint)idElm.GetInt64();
                        bg.GMS2TileIds.Add(tileId);
                    }
                }
                else if (tileIdsList.Count > 0)
                {
                    PrintLine($"[ImportTilesets] WARNING: Tile IDs count mismatch for '{tilesetName}' (expected {expectedCount}, got {tileIdsList.Count}), skipping tile IDs import");
                }
            }
        }

        jsonDoc.Dispose();
        tilesetsImported++;
        PrintLine($"[ImportTilesets] Updated tileset properties for: {tilesetName}");
    }
    catch (Exception e)
    {
        PrintLine($"[ImportTilesets] ERROR: Failed to import {jsonPath}: {e.Message}");
    }
}


string configFile = Path.Combine(tilesetsIn, "config.json");
if (File.Exists(configFile))
{
    PrintLine("[ImportTilesets] Found config.json, but it uses legacy format - please use individual JSON files instead.");
}


var tilesetFiles = Directory.GetFiles(tilesetsIn, "*.json")
    .Where(f => !f.EndsWith("config.json", StringComparison.OrdinalIgnoreCase))
    .ToArray();

foreach (var tilesetFile in tilesetFiles)
{
    ImportTilesetFromJson(tilesetFile);
}

PrintLine($"\n[ImportTilesets] Summary for Mod {ctx.ModNo ?? "N/A"}:");
PrintLine($"  Tilesets - Updated: {tilesetsImported}");
PrintLine("[ImportTilesets] Done.");
