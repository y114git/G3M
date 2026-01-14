#load "SharedPaths.csx"

using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;
using static UndertaleModLib.Models.UndertaleSound;
using static UndertaleModLib.UndertaleData;

void PrintLine(string s) => Console.WriteLine(s);

var ctx = PrepareImportContext();
string inputRoot = ctx.InputRoot;
string soundsIn = Path.Combine(inputRoot, "Sounds");

if (!Directory.Exists(soundsIn))
{
    PrintLine("[ImportSounds] No Sounds directory found, skipping.");
    return;
}

int imported = 0;
int skipped = 0;
int metadataApplied = 0;

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
        byte[] audioData = File.ReadAllBytes(soundFile);
        if (audioData == null || audioData.Length == 0)
        {
            PrintLine($"[ImportSounds] Failed to read {soundName}: empty file");
            skipped++;
            continue;
        }

        bool embedSound = isWAV || isOGG;

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
        }

        
        string metaFile = Path.Combine(soundsIn, soundName + ".json");
        if (File.Exists(metaFile))
        {
            try
            {
                string jsonContent = File.ReadAllText(metaFile, Encoding.UTF8);
                JsonDocument jsonDoc = JsonDocument.Parse(jsonContent);
                JsonElement root = jsonDoc.RootElement;

                
                if (root.TryGetProperty("volume", out JsonElement volumeElm))
                {
                    existingSound.Volume = (float)volumeElm.GetDouble();
                }

                
                if (root.TryGetProperty("pitch", out JsonElement pitchElm))
                {
                    existingSound.Pitch = (float)pitchElm.GetDouble();
                }

                
                if (root.TryGetProperty("preload", out JsonElement preloadElm))
                {
                    existingSound.Preload = preloadElm.GetBoolean();
                }

                
                if (root.TryGetProperty("effects", out JsonElement effectsElm))
                {
                    existingSound.Effects = (uint)effectsElm.GetInt32();
                }

                
                if (root.TryGetProperty("flags", out JsonElement flagsElm))
                {
                    uint flagsValue = (uint)flagsElm.GetInt32();
                    existingSound.Flags = (AudioEntryFlags)flagsValue;
                }

                
                if (root.TryGetProperty("audioGroupName", out JsonElement audioGroupNameElm))
                {
                    string audioGroupName = audioGroupNameElm.GetString();
                    if (!string.IsNullOrEmpty(audioGroupName) && Data.AudioGroups != null)
                    {
                        var audioGroup = Data.AudioGroups.ByName(audioGroupName);
                        if (audioGroup != null)
                        {
                            existingSound.AudioGroup = audioGroup;
                        }
                    }
                }

                
                if (root.TryGetProperty("audioLength", out JsonElement audioLengthElm) && Data.IsVersionAtLeast(2024, 6))
                {
                    existingSound.AudioLength = (float)audioLengthElm.GetDouble();
                }

                jsonDoc.Dispose();
                metadataApplied++;
                PrintLine($"[Sound] {soundName}: IMPORTED with metadata ({Path.GetExtension(filename)}, embedded: {embedSound})");
            }
            catch (Exception metaEx)
            {
                PrintLine($"[ImportSounds] Warning: Failed to apply metadata for {soundName}: {metaEx.Message}");
                PrintLine($"[Sound] {soundName}: IMPORTED without metadata ({Path.GetExtension(filename)}, embedded: {embedSound})");
            }
        }
        else
        {
            PrintLine($"[Sound] {soundName}: IMPORTED ({Path.GetExtension(filename)}, embedded: {embedSound})");
        }

        imported++;
    }
    catch (Exception ex)
    {
        PrintLine($"[ImportSounds] Failed to import {soundName}: {ex.Message}");
        skipped++;
    }
}

PrintLine($"[ImportSounds] Summary: {imported} imported ({metadataApplied} with metadata), {skipped} skipped");
