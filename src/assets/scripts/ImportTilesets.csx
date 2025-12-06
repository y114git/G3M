
#load "SharedPaths.csx"

using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

object GetProp(object obj, string name)
    => obj?.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase)?.GetValue(obj);

void SetProp(object obj, string name, object value)
{
    var prop = obj?.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase);
    if (prop != null && prop.CanWrite)
    {
        prop.SetValue(obj, value);
    }
}

var ctx = PrepareImportContext();
string inputRoot = ctx.InputRoot;
Console.WriteLine($"[ImportTilesets] Using Objects directory: {inputRoot}");

string tilesetsIn = Path.Combine(inputRoot, "Tilesets");

if (!Directory.Exists(tilesetsIn))
{
    PrintLine("[ImportTilesets] No Tilesets directory found, skipping.");
    return;
}


int ExtractJsonInt(string json, string key, int defaultValue = 0)
{
    var pattern = $"\"{key}\"\\s*:\\s*(-?\\d+)";
    var match = Regex.Match(json, pattern);
    return match.Success ? int.Parse(match.Groups[1].Value) : defaultValue;
}

uint ExtractJsonUInt(string json, string key, uint defaultValue = 0)
{
    var pattern = $"\"{key}\"\\s*:\\s*(\\d+)";
    var match = Regex.Match(json, pattern);
    return match.Success ? uint.Parse(match.Groups[1].Value) : defaultValue;
}

bool ExtractJsonBool(string json, string key, bool defaultValue = false)
{
    var pattern = $"\"{key}\"\\s*:\\s*(true|false)";
    var match = Regex.Match(json, pattern);
    if (!match.Success) return defaultValue;
    return match.Groups[1].Value == "true";
}

long ExtractJsonLong(string json, string key, long defaultValue = 0)
{
    var pattern = $"\"{key}\"\\s*:\\s*(-?\\d+)";
    var match = Regex.Match(json, pattern);
    return match.Success ? long.Parse(match.Groups[1].Value) : defaultValue;
}


void ImportTilesetPropertiesFromJson(UndertaleBackground bg, string json)
{
    if (bg == null || string.IsNullOrEmpty(json))
        return;
    
    
    uint currentTileCount = (uint)(GetProp(bg, "TileCount") ?? 0);
    uint currentTileWidth = (uint)(GetProp(bg, "TileWidth") ?? 32);
    uint currentTileHeight = (uint)(GetProp(bg, "TileHeight") ?? 32);
    uint currentBorderX = (uint)(GetProp(bg, "BorderX") ?? 0);
    uint currentBorderY = (uint)(GetProp(bg, "BorderY") ?? 0);
    uint currentTileColumn = (uint)(GetProp(bg, "TileColumn") ?? 10);
    uint currentItemPerTile = (uint)(GetProp(bg, "ItemPerTile") ?? 1);
    bool currentTransparent = (bool)(GetProp(bg, "Transparent") ?? false);
    bool currentSmooth = (bool)(GetProp(bg, "Smooth") ?? false);
    bool currentPreload = (bool)(GetProp(bg, "Preload") ?? false);
    long currentFrametime = (long)(GetProp(bg, "Frametime") ?? 0);
    
    
    SetProp(bg, "TileCount", ExtractJsonUInt(json, "tile_count", currentTileCount));
    SetProp(bg, "TileWidth", ExtractJsonUInt(json, "tile_width", currentTileWidth));
    SetProp(bg, "TileHeight", ExtractJsonUInt(json, "tile_height", currentTileHeight));
    SetProp(bg, "BorderX", ExtractJsonUInt(json, "border_x", currentBorderX));
    SetProp(bg, "BorderY", ExtractJsonUInt(json, "border_y", currentBorderY));
    SetProp(bg, "TileColumn", ExtractJsonUInt(json, "tile_column", currentTileColumn));
    SetProp(bg, "ItemPerTile", ExtractJsonUInt(json, "item_per_tile", currentItemPerTile));
    SetProp(bg, "Transparent", ExtractJsonBool(json, "transparent", currentTransparent));
    SetProp(bg, "Smooth", ExtractJsonBool(json, "smooth", currentSmooth));
    SetProp(bg, "Preload", ExtractJsonBool(json, "preload", currentPreload));
    SetProp(bg, "Frametime", ExtractJsonLong(json, "frametime", currentFrametime));
}


void ImportTilesetProperties(string filePath)
{
    string json = ReadAllTextSafe(filePath);
    if (string.IsNullOrEmpty(json))
    {
        PrintLine($"[ImportTilesets] ERROR: Failed to read {filePath}");
        return;
    }
    
    string tilesetName = Path.GetFileNameWithoutExtension(filePath);
    UndertaleBackground bg = Data.Backgrounds.ByName(tilesetName);
    
    if (bg == null)
    {
        PrintLine($"[ImportTilesets] WARNING: Background '{tilesetName}' not found, skipping properties import");
        return;
    }
    
    ImportTilesetPropertiesFromJson(bg, json);
    PrintLine($"[ImportTilesets] Updated tileset properties for: {tilesetName}");
}


string configFile = Path.Combine(tilesetsIn, "config.json");
if (File.Exists(configFile))
{
    try
    {
        string configJson = ReadAllTextSafe(configFile);
        if (!string.IsNullOrEmpty(configJson))
        {
            
            var tilesetPattern = @"""([^""]+)""\s*:\s*\{";
            var tilesetMatches = Regex.Matches(configJson, tilesetPattern);
            
            foreach (Match tilesetMatch in tilesetMatches)
            {
                string tilesetName = tilesetMatch.Groups[1].Value;
                UndertaleBackground bg = Data.Backgrounds.ByName(tilesetName);
                
                if (bg == null)
                {
                    PrintLine($"[ImportTilesets] WARNING: Background '{tilesetName}' not found in config.json, skipping");
                    continue;
                }
                
                
                int startPos = tilesetMatch.Index + tilesetMatch.Length;
                int depth = 1;
                int endPos = startPos;
                for (int i = startPos; i < configJson.Length && depth > 0; i++)
                {
                    if (configJson[i] == '{') depth++;
                    else if (configJson[i] == '}') depth--;
                    if (depth == 0) { endPos = i; break; }
                }
                
                if (endPos > startPos)
                {
                    string propertiesJson = configJson.Substring(startPos, endPos - startPos);
                    ImportTilesetPropertiesFromJson(bg, propertiesJson);
                    PrintLine($"[ImportTilesets] Updated tileset properties from config.json: {tilesetName}");
                }
            }
        }
    }
    catch (Exception e)
    {
        PrintLine($"[ImportTilesets] ERROR: Failed to import config.json: {e.Message}");
    }
}


int tilesetsImported = 0;

if (Directory.Exists(tilesetsIn))
{
    var tilesetFiles = Directory.GetFiles(tilesetsIn, "*.json").Where(f => !f.EndsWith("config.json", StringComparison.OrdinalIgnoreCase)).ToArray();
    foreach (var tilesetFile in tilesetFiles)
    {
        try
        {
            ImportTilesetProperties(tilesetFile);
            tilesetsImported++;
        }
        catch (Exception e)
        {
            PrintLine($"[ImportTilesets] ERROR: Failed to import {tilesetFile}: {e.Message}");
        }
    }
}


Data.SaveFile(Data.FilePath);

PrintLine($"\n[ImportTilesets] Summary for Mod {modNo}:");
PrintLine($"  Tilesets - Updated: {tilesetsImported}");
PrintLine("[ImportTilesets] Done.");

