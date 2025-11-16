
using System;
using System.IO;
using System.Text;
using System.Linq;
using System.Collections.Generic;
using System.Reflection;
using UndertaleModLib;
using UndertaleModLib.Models;

void PrintLine(string s) => Console.WriteLine(s);
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string ReadAllTextSafe(string path)
{
    try { return File.ReadAllText(path).Trim(); } catch { return null; }
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
if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
    throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

string comparisonPath = null;
if (modNo != "0" && modNo != "1")
{
    int modNum = int.Parse(modNo);
    string previousModPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, (modNum - 1).ToString(), "data.win");
    if (File.Exists(previousModPath))
    {
        comparisonPath = previousModPath;
    }
}
if (comparisonPath == null)
{
    comparisonPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, "0", "data.win");
}

string modRoot         = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string outputRoot      = Path.Combine(modRoot, "Objects");
string soundsOut       = Path.Combine(outputRoot, "Sounds");

Directory.CreateDirectory(outputRoot);
Directory.CreateDirectory(soundsOut);

UndertaleData comparison = null;
Dictionary<string, UndertaleSound> comparisonSounds = new Dictionary<string, UndertaleSound>();
if (File.Exists(comparisonPath))
{
    PrintLine($"[ExportSounds] Loading comparison file from: {comparisonPath}");
    using (var fs = new FileStream(comparisonPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        comparison = UndertaleIO.Read(fs);
    if (comparison != null)
    {
        foreach (var sound in comparison.Sounds)
        {
            if (sound?.Name?.Content != null)
                comparisonSounds[sound.Name.Content] = sound;
        }
    }
}

byte[] EMPTY_WAV_FILE_BYTES = Convert.FromBase64String("UklGRiQAAABXQVZFZm10IBAAAAABAAIAQB8AAAB9AAAEABAAZGF0YQAAAAA=");
string DEFAULT_AUDIOGROUP_NAME = "audiogroup_default";

Dictionary<string, IList<UndertaleEmbeddedAudio>> loadedAudioGroups = null;
IList<UndertaleEmbeddedAudio> GetAudioGroupData(UndertaleSound sound, UndertaleData data)
{
    loadedAudioGroups ??= new Dictionary<string, IList<UndertaleEmbeddedAudio>>();

    string audioGroupName = sound.AudioGroup is not null ? sound.AudioGroup.Name.Content : DEFAULT_AUDIOGROUP_NAME;
    if (loadedAudioGroups.ContainsKey(audioGroupName))
    {
        return loadedAudioGroups[audioGroupName];
    }

    string relativeAudioGroupPath;
    if (sound.AudioGroup is UndertaleAudioGroup { Path.Content: string customRelativePath })
    {
        relativeAudioGroupPath = customRelativePath;
    }
    else
    {
        relativeAudioGroupPath = $"audiogroup{sound.GroupID}.dat";
    }
    string groupFilePath = Path.Combine(Path.GetDirectoryName(comparisonPath), relativeAudioGroupPath);
    if (!File.Exists(groupFilePath))
    {
        return null;
    }

    try
    {
        UndertaleData groupData = null;
        using (var stream = new FileStream(groupFilePath, FileMode.Open, FileAccess.Read))
        {
            groupData = UndertaleIO.Read(stream);
        }
        loadedAudioGroups[audioGroupName] = groupData.EmbeddedAudio;
        return groupData.EmbeddedAudio;
    }
    catch (Exception e)
    {
        PrintLine($"[ExportSounds] Error loading {audioGroupName}: {e.Message}");
        return null;
    }
}

byte[] GetSoundData(UndertaleSound sound, UndertaleData data)
{
    if (sound.AudioFile is not null)
    {
        return sound.AudioFile.Data;
    }

    if (sound.GroupID > data.GetBuiltinSoundGroupID())
    {
        IList<UndertaleEmbeddedAudio> audioGroup = GetAudioGroupData(sound, data);
        if (audioGroup is not null && sound.AudioID < audioGroup.Count)
        {
            return audioGroup[sound.AudioID].Data;
        }
    }

    return EMPTY_WAV_FILE_BYTES;
}

int exported = 0;
int skipped = 0;

foreach (var sound in Data.Sounds)
{
    if (sound?.Name?.Content == null) continue;
    string name = SafeName(sound.Name.Content);
    
    bool shouldExport = false;
    if (!comparisonSounds.ContainsKey(sound.Name.Content))
    {
        shouldExport = true;
        PrintLine($"[Sound] {name}: NEW (not in comparison)");
    }
    else
    {
        var compSound = comparisonSounds[sound.Name.Content];
        if (sound.Flags != compSound.Flags ||
            sound.Volume != compSound.Volume ||
            sound.Pitch != compSound.Pitch ||
            sound.GroupID != compSound.GroupID ||
            sound.AudioID != compSound.AudioID ||
            sound.Name.Content != compSound.Name.Content)
        {
            shouldExport = true;
            PrintLine($"[Sound] {name}: MODIFIED");
        }
        else
        {
            byte[] currentData = GetSoundData(sound, Data);
            byte[] compData = GetSoundData(compSound, comparison);
            if (!currentData.SequenceEqual(compData))
            {
                shouldExport = true;
                PrintLine($"[Sound] {name}: MODIFIED (audio data differs)");
            }
            else
            {
                DebugLog($"[ExportSounds] Skipping {name}: unchanged");
                skipped++;
                continue;
            }
        }
    }
    
    if (!shouldExport) continue;
    
    try
    {
        bool flagCompressed = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsCompressed);
        bool flagEmbedded = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsEmbedded);
        string audioExt = ".ogg";
        bool isEmbedded = true;
        
        if (flagEmbedded && !flagCompressed)
        {
            audioExt = ".wav";
        }
        else if (!flagCompressed && !flagEmbedded)
        {
            audioExt = ".ogg";
            isEmbedded = false;
        }
        
        if (isEmbedded)
        {
            byte[] soundData = GetSoundData(sound, Data);
            string soundFile = Path.Combine(soundsOut, name + audioExt);
            File.WriteAllBytes(soundFile, soundData);
        }
        
        PrintLine($"[Sound] {name}: EXPORTED ({audioExt}, embedded: {isEmbedded})");
        exported++;
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportSounds] Failed to export {name}: {ex.Message}");
        skipped++;
    }
}

PrintLine($"[ExportSounds] Summary: {exported} exported, {skipped} skipped");

