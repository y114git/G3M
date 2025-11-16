
using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;
using static UndertaleModLib.Models.UndertaleSound;
using static UndertaleModLib.UndertaleData;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string ReadAllTextSafe(string path)
{
    try { return File.ReadAllText(path, Encoding.UTF8); } catch { return null; }
}

byte[] ReadAllBytesSafe(string path)
{
    try { return File.ReadAllBytes(path); } catch { return null; }
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
        Console.WriteLine($"[ImportSounds] Using Objects directory next to data.win: {inputRoot}");
    }
}

if (inputRoot == null)
{
    if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

    string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
    inputRoot = Path.Combine(modRoot, "Objects");
    Console.WriteLine($"[ImportSounds] Using Objects directory from modNumbersCache: {inputRoot}");
}

string soundsIn = Path.Combine(inputRoot, "Sounds");

if (!Directory.Exists(soundsIn))
{
    PrintLine("[ImportSounds] No Sounds directory found, skipping.");
    return;
}

bool usesAGRP = (Data.AudioGroups?.Count ?? 0) > 0;
string DEFAULT_AUDIOGROUP_NAME = "audiogroup_default";

int imported = 0;
int skipped = 0;

SyncBinding("AudioGroups, EmbeddedAudio, Sounds, Strings", true);

string[] soundFiles = Directory.GetFiles(soundsIn, "*.*", SearchOption.TopDirectoryOnly)
    .Where(f => f.EndsWith(".ogg", StringComparison.OrdinalIgnoreCase) || f.EndsWith(".wav", StringComparison.OrdinalIgnoreCase))
    .ToArray();

foreach (string soundFile in soundFiles)
{
    string filename = Path.GetFileName(soundFile);
    string soundName = Path.GetFileNameWithoutExtension(filename);
    bool isOGG = Path.GetExtension(filename).ToLower() == ".ogg";
    bool isWAV = Path.GetExtension(filename).ToLower() == ".wav";
    
    if (!isOGG && !isWAV)
    {
        skipped++;
        continue;
    }
    
    UndertaleSound existingSound = Data.Sounds.ByName(soundName);
    if (existingSound == null)
    {
        PrintLine($"[ImportSounds] Sound '{soundName}' not found in game, skipping (cannot create new sounds)");
        skipped++;
        continue;
    }
    
    try
    {
        byte[] audioData = ReadAllBytesSafe(soundFile);
        if (audioData == null || audioData.Length == 0)
        {
            PrintLine($"[ImportSounds] Failed to read {soundName}: empty file");
            skipped++;
            continue;
        }
        
        bool embedSound = isWAV || (isOGG && true);
        bool decodeLoad = false;
        
        if (embedSound)
        {
            if (existingSound.AudioFile == null)
            {
                existingSound.AudioFile = new UndertaleEmbeddedAudio();
            }
            
            existingSound.AudioFile.Data = audioData;
            existingSound.Flags |= AudioEntryFlags.IsEmbedded;
            
            if (!isOGG)
            {
                existingSound.Flags &= ~AudioEntryFlags.IsCompressed;
            }
            else
            {
                existingSound.Flags |= AudioEntryFlags.IsCompressed;
            }
            
            if (decodeLoad)
            {
                existingSound.Flags |= AudioEntryFlags.UncompressOnLoad;
            }
            else
            {
                existingSound.Flags &= ~AudioEntryFlags.UncompressOnLoad;
            }
        }
        
        PrintLine($"[Sound] {soundName}: IMPORTED ({Path.GetExtension(filename)}, embedded: {embedSound})");
        imported++;
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportSounds] Failed to import {soundName}: {ex.Message}");
        skipped++;
    }
}

PrintLine($"[ImportSounds] Summary: {imported} imported, {skipped} skipped");

