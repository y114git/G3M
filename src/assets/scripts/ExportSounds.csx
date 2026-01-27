


using System;
using System.IO;
using System.Text;
using System.Text.Json;
using System.Linq;
using System.Threading.Tasks;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;




void PrintLine(string s) => Console.WriteLine(s);

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

string GetOutputDirectory()
{
    string outputDir = Environment.GetEnvironmentVariable("OUTPUT_DIR");
    if (string.IsNullOrEmpty(outputDir))
        throw new ScriptException("OUTPUT_DIR environment variable is not set.");
    if (!Directory.Exists(outputDir))
        Directory.CreateDirectory(outputDir);
    return outputDir;
}

byte[] EMPTY_WAV_FILE_BYTES = Convert.FromBase64String("UklGRiQAAABXQVZFZm10IBAAAAABAAIAQB8AAAB9AAAEABAAZGF0YQAAAAA=");
string DEFAULT_AUDIOGROUP_NAME = "audiogroup_default";

Dictionary<string, IList<UndertaleEmbeddedAudio>> loadedAudioGroups = new Dictionary<string, IList<UndertaleEmbeddedAudio>>();

IList<UndertaleEmbeddedAudio> GetAudioGroupData(UndertaleSound sound, UndertaleData data, string dataFilePath)
{
    string audioGroupName = sound.AudioGroup is not null ? sound.AudioGroup.Name.Content : DEFAULT_AUDIOGROUP_NAME;
    if (loadedAudioGroups.ContainsKey(audioGroupName))
        return loadedAudioGroups[audioGroupName];

    string relativeAudioGroupPath;
    if (sound.AudioGroup is UndertaleAudioGroup { Path.Content: string customRelativePath })
        relativeAudioGroupPath = customRelativePath;
    else
        relativeAudioGroupPath = $"audiogroup{sound.GroupID}.dat";

    string groupFilePath = Path.Combine(Path.GetDirectoryName(dataFilePath), relativeAudioGroupPath);
    if (!File.Exists(groupFilePath))
        return null;

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

byte[] GetSoundData(UndertaleSound sound, UndertaleData data, string dataFilePath)
{
    if (sound.AudioFile is not null)
        return sound.AudioFile.Data;

    if (sound.GroupID > data.GetBuiltinSoundGroupID())
    {
        IList<UndertaleEmbeddedAudio> audioGroup = GetAudioGroupData(sound, data, dataFilePath);
        if (audioGroup is not null && sound.AudioID < audioGroup.Count)
            return audioGroup[sound.AudioID].Data;
    }

    return EMPTY_WAV_FILE_BYTES;
}




EnsureDataLoaded();

string soundsOut = GetOutputDirectory();
PrintLine($"[ExportSounds] Exporting to: {soundsOut}");

List<UndertaleSound> allSounds = Data.Sounds.ToList();
PrintLine($"[ExportSounds] Found {allSounds.Count} sounds to export.");

JsonSerializerOptions jsonWriteOptions = new JsonSerializerOptions 
{ 
    WriteIndented = true,
    Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping
};

SetProgressBar(null, "Exporting Sounds", 0, allSounds.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allSounds, sound => ExportSound(sound, soundsOut)));

void ExportSound(UndertaleSound sound, string outputDir)
{
    if (sound?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(sound.Name.Content);

        bool flagCompressed = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsCompressed);
        bool flagEmbedded = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsEmbedded);
        string audioExt = ".ogg";
        bool isEmbedded = true;

        if (flagEmbedded && !flagCompressed)
            audioExt = ".wav";
        else if (!flagCompressed && !flagEmbedded)
        {
            audioExt = ".ogg";
            isEmbedded = false;
        }

        
        if (isEmbedded)
        {
            byte[] soundData = GetSoundData(sound, Data, FilePath);
            string soundFile = Path.Combine(outputDir, name + audioExt);
            File.WriteAllBytes(soundFile, soundData);
        }

        
        var soundMeta = new Dictionary<string, object>
        {
            ["name"] = sound.Name?.Content ?? "",
            ["flags"] = (uint)sound.Flags,
            ["flagsDescription"] = new Dictionary<string, bool>
            {
                ["isEmbedded"] = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsEmbedded),
                ["isCompressed"] = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsCompressed),
                ["isDecompressedOnLoad"] = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.IsDecompressedOnLoad),
                ["regular"] = sound.Flags.HasFlag(UndertaleSound.AudioEntryFlags.Regular)
            },
            ["type"] = sound.Type?.Content ?? "",
            ["file"] = sound.File?.Content ?? "",
            ["effects"] = sound.Effects,
            ["volume"] = sound.Volume,
            ["pitch"] = sound.Pitch,
            ["preload"] = sound.Preload,
            ["audioGroupName"] = sound.AudioGroup?.Name?.Content ?? "",
            ["groupId"] = sound.GroupID,
            ["audioId"] = sound.AudioID
        };

        if (Data.IsVersionAtLeast(2024, 6))
        {
            soundMeta["audioLength"] = sound.AudioLength;
        }

        string metaJson = JsonSerializer.Serialize(soundMeta, jsonWriteOptions);
        string metaFile = Path.Combine(outputDir, name + ".json");
        File.WriteAllText(metaFile, metaJson, Encoding.UTF8);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportSounds] Failed to export sound {sound.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportSounds] Export complete. {allSounds.Count} sounds exported to {soundsOut}");
