


using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Collections.Generic;
using UndertaleModLib;
using UndertaleModLib.Models;
using static UndertaleModLib.Models.UndertaleSound;
using static UndertaleModLib.UndertaleData;




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




EnsureDataLoaded();

string soundsIn = GetInputDirectory();
PrintLine($"[ImportSounds] Importing from: {soundsIn}");

int imported = 0;
int created = 0;
int skipped = 0;
int metadataApplied = 0;

SyncBinding("AudioGroups, EmbeddedAudio, Sounds, Strings", true);


var soundFilesSet = new HashSet<string>();
foreach (var file in Directory.GetFiles(soundsIn, "*.*", SearchOption.TopDirectoryOnly))
{
    string ext = Path.GetExtension(file).ToLowerInvariant();
    if (ext == ".ogg" || ext == ".wav" || ext == ".json")
    {
        string baseName = Path.GetFileNameWithoutExtension(file);
        soundFilesSet.Add(baseName);
    }
}

PrintLine($"[ImportSounds] Found {soundFilesSet.Count} sound(s) to process");

foreach (string soundName in soundFilesSet)
{
    string oggFile = Path.Combine(soundsIn, soundName + ".ogg");
    string wavFile = Path.Combine(soundsIn, soundName + ".wav");
    string metaFile = Path.Combine(soundsIn, soundName + ".json");
    
    
    string audioFile = null;
    bool isOGG = false;
    bool isWAV = false;
    
    if (File.Exists(oggFile))
    {
        audioFile = oggFile;
        isOGG = true;
    }
    else if (File.Exists(wavFile))
    {
        audioFile = wavFile;
        isWAV = true;
    }
    
    
    if (audioFile == null && !File.Exists(metaFile))
    {
        skipped++;
        continue;
    }
    
    
    if (audioFile == null && File.Exists(metaFile))
    {
        var existingSound = Data.Sounds.ByName(soundName);
        if (existingSound == null)
        {
            PrintLine($"[ImportSounds] Skipping {soundName}: no audio file and sound doesn't exist");
            skipped++;
            continue;
        }
        
        try
        {
            ApplyMetadata(existingSound, metaFile);
            metadataApplied++;
            PrintLine($"[Sound] {soundName}: metadata updated");
        }
        catch (Exception ex)
        {
            PrintLine($"[ImportSounds] Failed to apply metadata for {soundName}: {ex.Message}");
        }
        continue;
    }

    try
    {
        byte[] audioData = File.ReadAllBytes(audioFile);
        if (audioData == null || audioData.Length == 0)
        {
            PrintLine($"[ImportSounds] Failed to read {soundName}: empty file");
            skipped++;
            continue;
        }

        UndertaleSound sound = Data.Sounds.ByName(soundName);
        bool isNew = false;

        if (sound == null)
        {
            
            sound = new UndertaleSound();
            sound.Name = Data.Strings.MakeString(soundName);
            sound.File = Data.Strings.MakeString(soundName + (isOGG ? ".ogg" : ".wav"));
            sound.Type = isOGG ? Data.Strings.MakeString(".ogg") : Data.Strings.MakeString(".wav");
            sound.Volume = 1.0f;
            sound.Pitch = 1.0f;
            sound.Preload = true;
            sound.Flags = AudioEntryFlags.IsEmbedded;
            if (isOGG)
            {
                sound.Flags |= AudioEntryFlags.IsCompressed;
            }
            
            
            sound.AudioFile = new UndertaleEmbeddedAudio();
            sound.AudioFile.Data = audioData;
            
            
            Data.EmbeddedAudio.Add(sound.AudioFile);
            sound.AudioID = Data.EmbeddedAudio.Count - 1;
            
            
            if (Data.AudioGroups != null && Data.AudioGroups.Count > 0)
            {
                sound.AudioGroup = Data.AudioGroups[0];
                sound.GroupID = 0;
            }
            
            isNew = true;
            created++;
            PrintLine($"[ImportSounds] Creating NEW sound: {soundName}");
        }
        else
        {
            
            if (sound.AudioFile == null)
            {
                sound.AudioFile = new UndertaleEmbeddedAudio();
                Data.EmbeddedAudio.Add(sound.AudioFile);
                sound.AudioID = Data.EmbeddedAudio.Count - 1;
            }
            sound.AudioFile.Data = audioData;
            
            
            sound.Flags |= AudioEntryFlags.IsEmbedded;
            if (isOGG)
            {
                sound.Flags |= AudioEntryFlags.IsCompressed;
            }
            else
            {
                sound.Flags &= ~AudioEntryFlags.IsCompressed;
            }
        }

        
        if (File.Exists(metaFile))
        {
            try
            {
                ApplyMetadata(sound, metaFile);
                metadataApplied++;
            }
            catch (Exception metaEx)
            {
                PrintLine($"[ImportSounds] Warning: Failed to apply metadata for {soundName}: {metaEx.Message}");
            }
        }
        
        if (isNew)
        {
            Data.Sounds.Add(sound);
            PrintLine($"[Sound] {soundName}: CREATED and added to Data.Sounds");
        }
        else
        {
            PrintLine($"[Sound] {soundName}: UPDATED");
        }

        imported++;
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportSounds] Failed to import {soundName}: {ex.Message}");
        skipped++;
    }
}

PrintLine($"[ImportSounds] Summary: {imported} imported ({created} new, {metadataApplied} with metadata), {skipped} skipped");

void ApplyMetadata(UndertaleSound sound, string metaFile)
{
    string jsonContent = File.ReadAllText(metaFile, Encoding.UTF8);
    JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
    JsonElement root = jsonDoc.RootElement;

    if (root.TryGetProperty("volume", out JsonElement volumeElm))
    {
        sound.Volume = (float)volumeElm.GetDouble();
    }

    if (root.TryGetProperty("pitch", out JsonElement pitchElm))
    {
        sound.Pitch = (float)pitchElm.GetDouble();
    }

    if (root.TryGetProperty("preload", out JsonElement preloadElm))
    {
        sound.Preload = preloadElm.GetBoolean();
    }

    if (root.TryGetProperty("effects", out JsonElement effectsElm))
    {
        sound.Effects = (uint)effectsElm.GetInt32();
    }

    if (root.TryGetProperty("flags", out JsonElement flagsElm))
    {
        uint flagsValue = (uint)flagsElm.GetInt32();
        sound.Flags = (AudioEntryFlags)flagsValue;
    }

    if (root.TryGetProperty("audioGroupName", out JsonElement audioGroupNameElm))
    {
        string audioGroupName = audioGroupNameElm.GetString();
        if (!string.IsNullOrEmpty(audioGroupName) && Data.AudioGroups != null)
        {
            var audioGroup = Data.AudioGroups.ByName(audioGroupName);
            if (audioGroup != null)
            {
                sound.AudioGroup = audioGroup;
                sound.GroupID = Data.AudioGroups.IndexOf(audioGroup);
            }
        }
    }

    if (root.TryGetProperty("audioLength", out JsonElement audioLengthElm) && Data.IsVersionAtLeast(2024, 6))
    {
        sound.AudioLength = (float)audioLengthElm.GetDouble();
    }

    jsonDoc.Dispose();
}

