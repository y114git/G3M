

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

EnsureDataLoaded();


string deltahubRoot = null;
{
    var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (probe != null)
    {
        if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
        probe = probe.Parent;
    }
    if (deltahubRoot == null) throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}


string chapterNo = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo     = ReadAllTextSafe(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));




string inputRoot = null;
if (!string.IsNullOrEmpty(FilePath))
{
    string dataWinDir = Path.GetDirectoryName(FilePath);
    string objectsNextToDataWin = Path.Combine(dataWinDir, "Objects");
    if (Directory.Exists(objectsNextToDataWin))
    {
        inputRoot = objectsNextToDataWin;
        Console.WriteLine($"[ImportNewObjects] Using Objects directory next to data.win: {inputRoot}");
    }
}


if (inputRoot == null)
{
    if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

    string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
    inputRoot = Path.Combine(modRoot, "Objects");
    Console.WriteLine($"[ImportNewObjects] Using Objects directory from modNumbersCache: {inputRoot}");
}

string newObjectsIn = Path.Combine(inputRoot, "NewObjects");

if (!Directory.Exists(newObjectsIn))
{
    PrintLine("[ImportNewObjects] No NewObjects directory found, skipping.");
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


void ImportNewObject(string filePath)
{
    string json = ReadAllTextSafe(filePath);
    if (string.IsNullOrEmpty(json))
    {
        PrintLine($"[ImportNewObjects] ERROR: Failed to read {filePath}");
        return;
    }
    
    string objectName = ExtractJsonString(json, "name");
    if (string.IsNullOrEmpty(objectName))
    {
        objectName = Path.GetFileNameWithoutExtension(filePath);
    }
    
    
    if (Data.GameObjects.ByName(objectName) != null)
    {
        PrintLine($"[ImportNewObjects] WARNING: Object '{objectName}' already exists, skipping (use ImportExistingObjects to modify)");
        return;
    }
    
    
    UndertaleGameObject obj = new UndertaleGameObject();
    obj.Name = new UndertaleString(objectName);
    Data.Strings.Add(obj.Name);
    
    
    string spriteName = ExtractJsonStringOrNull(json, "sprite");
    if (!string.IsNullOrEmpty(spriteName))
    {
        obj.Sprite = Data.Sprites.ByName(spriteName);
    }
    
    
    obj.Solid = ExtractJsonBool(json, "solid", false);
    obj.Visible = ExtractJsonBool(json, "visible", true);
    obj.Persistent = ExtractJsonBool(json, "persistent", false);
    obj.Depth = ExtractJsonFloat(json, "depth", 0.0f);
    
    
    string parentName = ExtractJsonStringOrNull(json, "parent");
    if (!string.IsNullOrEmpty(parentName))
    {
        obj.ParentObject = Data.GameObjects.ByName(parentName);
    }
    
    
    string eventsJson = ExtractJsonArray(json, "events");
    if (!string.IsNullOrEmpty(eventsJson))
    {
        
        
        PrintLine($"[ImportNewObjects] NOTE: Events for {objectName} should be imported via GML code entries");
    }
    
    
    Data.GameObjects.Add(obj);
    PrintLine($"[ImportNewObjects] Created new object: {objectName}");
}


string ExtractJsonArray(string json, string key)
{
    var pattern = $"\"{key}\"\\s*:\\s*\\[([^\\]]*)\\]";
    var match = Regex.Match(json, pattern, RegexOptions.Singleline);
    return match.Success ? match.Groups[1].Value : "";
}


int objectsImported = 0;

if (Directory.Exists(newObjectsIn))
{
    var objectFiles = Directory.GetFiles(newObjectsIn, "*.json");
    foreach (var objectFile in objectFiles)
    {
        try
        {
            ImportNewObject(objectFile);
            objectsImported++;
        }
        catch (Exception e)
        {
            PrintLine($"[ImportNewObjects] ERROR: Failed to import {objectFile}: {e.Message}");
            PrintLine($"[ImportNewObjects] Stack trace: {e.StackTrace}");
        }
    }
}


Data.SaveFile(Data.FilePath);

PrintLine($"\n[ImportNewObjects] Summary for Mod {modNo}:");
PrintLine($"  New Objects - Created: {objectsImported}");
PrintLine("[ImportNewObjects] Done.");

