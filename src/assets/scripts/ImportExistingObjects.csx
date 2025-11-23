

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

string ReadAllTextSafe(string path)
{
    try { return File.ReadAllText(path, Encoding.UTF8); } catch { return null; }
}

#load "SharedPaths.csx"

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
        Console.WriteLine($"[ImportExistingObjects] Using Objects directory next to data.win: {inputRoot}");
    }
}


if (inputRoot == null)
{
    if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

    string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
    inputRoot = Path.Combine(modRoot, "Objects");
    Console.WriteLine($"[ImportExistingObjects] Using Objects directory from modNumbersCache: {inputRoot}");
}

string existingObjectsIn = Path.Combine(inputRoot, "ExistingObjects");

if (!Directory.Exists(existingObjectsIn))
{
    PrintLine("[ImportExistingObjects] No ExistingObjects directory found, skipping.");
    return;
}


string ExtractJsonString(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\"([^\"]*)\"";
    var match = Regex.Match(json, pattern);
    return match.Success ? match.Groups[1].Value : null;
}

string ExtractJsonStringOrNull(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*(null|\"([^\"]*)\")";
    var match = Regex.Match(json, pattern);
    if (!match.Success) return null;
    if (match.Groups[1].Value == "null") return null;
    return match.Groups[2].Value;
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

float ExtractJsonFloat(string json, string key, float defaultValue = 0.0f)
{
    var pattern = $"\"{key}\"\\s*:\\s*(-?\\d+\\.?\\d*)";
    var match = Regex.Match(json, pattern);
    return match.Success ? float.Parse(match.Groups[1].Value) : defaultValue;
}


void ModifyExistingObject(string filePath)
{
    string json = ReadAllTextSafe(filePath);
    if (string.IsNullOrEmpty(json))
    {
        PrintLine($"[ImportExistingObjects] ERROR: Failed to read {filePath}");
        return;
    }
    
    string objectName = ExtractJsonString(json, "name");
    if (string.IsNullOrEmpty(objectName))
    {
        objectName = Path.GetFileNameWithoutExtension(filePath);
    }
    
    
    UndertaleGameObject obj = Data.GameObjects.ByName(objectName);
    if (obj == null)
    {
        PrintLine($"[ImportExistingObjects] WARNING: Object '{objectName}' not found, skipping (use ImportNewObjects to create)");
        return;
    }
    
    PrintLine($"[ImportExistingObjects] Modifying existing object: {objectName}");
    
    
    string spriteName = ExtractJsonStringOrNull(json, "sprite");
    if (!string.IsNullOrEmpty(spriteName))
    {
        obj.Sprite = Data.Sprites.ByName(spriteName);
    }
    
    
    if (json.Contains("\"solid\""))
        obj.Solid = ExtractJsonBool(json, "solid", obj.Solid);
    if (json.Contains("\"visible\""))
        obj.Visible = ExtractJsonBool(json, "visible", obj.Visible);
    if (json.Contains("\"persistent\""))
        obj.Persistent = ExtractJsonBool(json, "persistent", obj.Persistent);
    if (json.Contains("\"depth\""))
        obj.Depth = ExtractJsonFloat(json, "depth", obj.Depth);
    
    
    string parentName = ExtractJsonStringOrNull(json, "parent");
    if (!string.IsNullOrEmpty(parentName))
    {
        obj.ParentObject = Data.GameObjects.ByName(parentName);
    }
    else if (json.Contains("\"parent\""))
    {
        
        obj.ParentObject = null;
    }
    
    
    string eventsJson = ExtractJsonArray(json, "events");
    if (!string.IsNullOrEmpty(eventsJson))
    {
        PrintLine($"[ImportExistingObjects] NOTE: Events for {objectName} should be modified via GML code entries");
    }
    
    PrintLine($"[ImportExistingObjects] Updated object: {objectName}");
}


string ExtractJsonArray(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\\[([^\\]]*)\\]";
    var match = Regex.Match(json, pattern, RegexOptions.Singleline);
    return match.Success ? match.Groups[1].Value : "";
}


int objectsModified = 0;

if (Directory.Exists(existingObjectsIn))
{
    var objectFiles = Directory.GetFiles(existingObjectsIn, "*.json");
    foreach (var objectFile in objectFiles)
    {
        try
        {
            ModifyExistingObject(objectFile);
            objectsModified++;
        }
        catch (Exception e)
        {
            PrintLine($"[ImportExistingObjects] ERROR: Failed to modify {objectFile}: {e.Message}");
            PrintLine($"[ImportExistingObjects] Stack trace: {e.StackTrace}");
        }
    }
}


Data.SaveFile(Data.FilePath);

PrintLine($"\n[ImportExistingObjects] Summary for Mod {modNo}:");
PrintLine($"  Existing Objects - Modified: {objectsModified}");
PrintLine("[ImportExistingObjects] Done.");

