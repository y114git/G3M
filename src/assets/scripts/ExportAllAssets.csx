#load "SharedPaths.csx"

using System.Text;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using UndertaleModLib;
using UndertaleModLib.Models;
using UndertaleModLib.Util;

void PrintLine(string s) => Console.WriteLine(s);

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

EnsureDataLoaded();

if (Data.IsYYC())
{
    PrintLine("[ExportAllAssets] YYC build detected – code export not available.");
    return;
}

string deltahubRoot = null;
try
{
    deltahubRoot = FindDeltahubRoot();
}
catch
{
    if (!string.IsNullOrEmpty(FilePath))
    {
        var dataWinDir = new DirectoryInfo(Path.GetDirectoryName(FilePath));
        var probe = dataWinDir;
        while (probe != null)
        {
            if (Directory.Exists(Path.Combine(probe.FullName, "output"))) { deltahubRoot = probe.FullName; break; }
            probe = probe.Parent;
        }
    }

    if (deltahubRoot == null)
    {
        var entryAssembly = Assembly.GetEntryAssembly();
        if (entryAssembly != null && !string.IsNullOrEmpty(entryAssembly.Location))
        {
            var firstParent = Directory.GetParent(entryAssembly.Location);
            if (firstParent != null)
            {
                var assemblyRoot = Directory.GetParent(firstParent.FullName);
                if (assemblyRoot != null && Directory.Exists(Path.Combine(assemblyRoot.FullName, "output")))
                {
                    deltahubRoot = assemblyRoot.FullName;
                }
            }
        }
    }

    if (deltahubRoot == null)
        throw new ScriptException("DELTAHUB root not found (no /output ancestor).");
}

string chapterNo = GetChapterNumber(deltahubRoot);
string modNo = GetModNumbersCache(deltahubRoot);

string modRoot = Path.Combine(deltahubRoot, "output", "DeltahubMergeWorkspace", chapterNo, modNo);
string outputRoot = Path.Combine(modRoot, "Objects");
Directory.CreateDirectory(outputRoot);

string codeFolder = Path.Combine(outputRoot, "CodeEntries");
string sprFolder = Path.Combine(outputRoot, "Sprites");
string fntFolder = Path.Combine(outputRoot, "Fonts");
string bgrFolder = Path.Combine(outputRoot, "Backgrounds");
string shadersOut = Path.Combine(outputRoot, "Shaders");
string soundsOut = Path.Combine(outputRoot, "Sounds");
string roomsOut = Path.Combine(outputRoot, "Rooms");
string audioGroupsOut = Path.Combine(outputRoot, "AudioGroups");
string pathsOut = Path.Combine(outputRoot, "Paths");
string timelinesOut = Path.Combine(outputRoot, "Timelines");
string extensionsOut = Path.Combine(outputRoot, "Extensions");

Directory.CreateDirectory(codeFolder);
Directory.CreateDirectory(sprFolder);
Directory.CreateDirectory(fntFolder);
Directory.CreateDirectory(bgrFolder);
Directory.CreateDirectory(shadersOut);
Directory.CreateDirectory(soundsOut);
Directory.CreateDirectory(roomsOut);
Directory.CreateDirectory(audioGroupsOut);
Directory.CreateDirectory(pathsOut);
Directory.CreateDirectory(timelinesOut);
Directory.CreateDirectory(extensionsOut);

PrintLine($"[ExportAllAssets] Starting full export for mod {modNo}...");

GlobalDecompileContext globalDecompileContext = new(Data);
Underanalyzer.Decompiler.IDecompileSettings decompilerSettings = Data.ToolInfo.DecompilerSettings;

void ExportShader(UndertaleShader shader, string outputDir)
{
    Directory.CreateDirectory(outputDir);

    string shaderType = shader.Type.ToString();
    File.WriteAllText(Path.Combine(outputDir, "Type.txt"), shaderType, Encoding.UTF8);

    if (shader.GLSL_ES_Fragment != null)
        File.WriteAllText(Path.Combine(outputDir, "GLSL_ES_Fragment.txt"), shader.GLSL_ES_Fragment.Content ?? "", Encoding.UTF8);
    if (shader.GLSL_ES_Vertex != null)
        File.WriteAllText(Path.Combine(outputDir, "GLSL_ES_Vertex.txt"), shader.GLSL_ES_Vertex.Content ?? "", Encoding.UTF8);
    if (shader.GLSL_Fragment != null)
        File.WriteAllText(Path.Combine(outputDir, "GLSL_Fragment.txt"), shader.GLSL_Fragment.Content ?? "", Encoding.UTF8);
    if (shader.GLSL_Vertex != null)
        File.WriteAllText(Path.Combine(outputDir, "GLSL_Vertex.txt"), shader.GLSL_Vertex.Content ?? "", Encoding.UTF8);
    if (shader.HLSL9_Fragment != null)
        File.WriteAllText(Path.Combine(outputDir, "HLSL9_Fragment.txt"), shader.HLSL9_Fragment.Content ?? "", Encoding.UTF8);
    if (shader.HLSL9_Vertex != null)
        File.WriteAllText(Path.Combine(outputDir, "HLSL9_Vertex.txt"), shader.HLSL9_Vertex.Content ?? "", Encoding.UTF8);

    if (shader.HLSL11_VertexData != null && !shader.HLSL11_VertexData.IsNull && shader.HLSL11_VertexData.Data != null && shader.HLSL11_VertexData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "HLSL11_VertexData.bin"), shader.HLSL11_VertexData.Data);
    if (shader.HLSL11_PixelData != null && !shader.HLSL11_PixelData.IsNull && shader.HLSL11_PixelData.Data != null && shader.HLSL11_PixelData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "HLSL11_PixelData.bin"), shader.HLSL11_PixelData.Data);
    if (shader.PSSL_VertexData != null && !shader.PSSL_VertexData.IsNull && shader.PSSL_VertexData.Data != null && shader.PSSL_VertexData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "PSSL_VertexData.bin"), shader.PSSL_VertexData.Data);
    if (shader.PSSL_PixelData != null && !shader.PSSL_PixelData.IsNull && shader.PSSL_PixelData.Data != null && shader.PSSL_PixelData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "PSSL_PixelData.bin"), shader.PSSL_PixelData.Data);
    if (shader.Cg_PSVita_VertexData != null && !shader.Cg_PSVita_VertexData.IsNull && shader.Cg_PSVita_VertexData.Data != null && shader.Cg_PSVita_VertexData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PSVita_VertexData.bin"), shader.Cg_PSVita_VertexData.Data);
    if (shader.Cg_PSVita_PixelData != null && !shader.Cg_PSVita_PixelData.IsNull && shader.Cg_PSVita_PixelData.Data != null && shader.Cg_PSVita_PixelData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PSVita_PixelData.bin"), shader.Cg_PSVita_PixelData.Data);
    if (shader.Cg_PS3_VertexData != null && !shader.Cg_PS3_VertexData.IsNull && shader.Cg_PS3_VertexData.Data != null && shader.Cg_PS3_VertexData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PS3_VertexData.bin"), shader.Cg_PS3_VertexData.Data);
    if (shader.Cg_PS3_PixelData != null && !shader.Cg_PS3_PixelData.IsNull && shader.Cg_PS3_PixelData.Data != null && shader.Cg_PS3_PixelData.Data.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PS3_PixelData.bin"), shader.Cg_PS3_PixelData.Data);

    if (shader.VertexShaderAttributes != null && shader.VertexShaderAttributes.Count > 0)
    {
        var attrs = new StringBuilder();
        for (int i = 0; i < shader.VertexShaderAttributes.Count; i++)
        {
            var attr = shader.VertexShaderAttributes[i];
            if (attr != null && attr.Name != null)
            {
                attrs.AppendLine(attr.Name.Content ?? "");
            }
        }
        File.WriteAllText(Path.Combine(outputDir, "VertexShaderAttributes.txt"), attrs.ToString(), Encoding.UTF8);
    }
}

byte[] EMPTY_WAV_FILE_BYTES = Convert.FromBase64String("UklGRiQAAABXQVZFZm10IBAAAAABAAIAQB8AAAB9AAAEABAAZGF0YQAAAAA=");
string DEFAULT_AUDIOGROUP_NAME = "audiogroup_default";

Dictionary<string, IList<UndertaleEmbeddedAudio>> loadedAudioGroups = null;
IList<UndertaleEmbeddedAudio> GetAudioGroupData(UndertaleSound sound, UndertaleData data, string comparisonPath)
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
        PrintLine($"[ExportAllAssets] Error loading {audioGroupName}: {e.Message}");
        return null;
    }
}

byte[] GetSoundData(UndertaleSound sound, UndertaleData data, string comparisonPath)
{
    if (sound.AudioFile is not null)
    {
        return sound.AudioFile.Data;
    }

    if (sound.GroupID > data.GetBuiltinSoundGroupID())
    {
        IList<UndertaleEmbeddedAudio> audioGroup = GetAudioGroupData(sound, data, comparisonPath);
        if (audioGroup is not null && sound.AudioID < audioGroup.Count)
        {
            return audioGroup[sound.AudioID].Data;
        }
    }

    return EMPTY_WAV_FILE_BYTES;
}

string comparisonPath = null;
if (modNo != "0")
{
    comparisonPath = Path.Combine(deltahubRoot, "output", "DeltahubMergeWorkspace", chapterNo, "0", "data.win");
}

List<UndertaleCode> allCode = Data.Code.Where(c => c.ParentEntry is null).ToList();
List<UndertaleSprite> allSprites = Data.Sprites.ToList();
List<UndertaleBackground> allBackgrounds = Data.Backgrounds.ToList();
List<UndertaleFont> allFonts = Data.Fonts.ToList();
List<UndertaleShader> allShaders = Data.Shaders.ToList();
List<UndertaleSound> allSounds = Data.Sounds.ToList();
List<UndertaleRoom> allRooms = Data.Rooms.ToList();
List<UndertaleAudioGroup> allAudioGroups = Data.AudioGroups?.ToList() ?? new List<UndertaleAudioGroup>();
List<UndertalePath> allPaths = Data.Paths?.ToList() ?? new List<UndertalePath>();
List<UndertaleTimeline> allTimelines = Data.Timelines?.ToList() ?? new List<UndertaleTimeline>();
List<UndertaleExtension> allExtensions = Data.Extensions?.ToList() ?? new List<UndertaleExtension>();

int totalItems = allCode.Count + allSprites.Count + allBackgrounds.Count + allFonts.Count + allShaders.Count + allSounds.Count + allRooms.Count + allAudioGroups.Count + allPaths.Count + allTimelines.Count + allExtensions.Count;

SetProgressBar(null, "Exporting All Assets", 0, totalItems);
StartProgressBarUpdater();

TextureWorker worker = null;
using (worker = new TextureWorker())
{
    await DumpCode();
    await DumpSprites();
    await DumpBackgrounds();
    await DumpFonts();
    await DumpShaders();
    await DumpSounds();
    await DumpTilesets();
    await DumpRooms();
    await DumpAudioGroups();
    await DumpPaths();
    await DumpTimelines();
    await DumpExtensions();
}

await StopProgressBarUpdater();
HideProgressBar();

async Task DumpCode()
{
    await Task.Run(() => Parallel.ForEach(allCode, DumpCodeItem));
}

void DumpCodeItem(UndertaleCode code)
{
    if (code is null) return;

    string path = Path.Combine(codeFolder, code.Name.Content + ".gml");
    try
    {
        File.WriteAllText(path, new Underanalyzer.Decompiler.DecompileContext(globalDecompileContext, code, decompilerSettings).DecompileToString());
    }
    catch (Exception e)
    {
        File.WriteAllText(path, "/*\nDECOMPILER FAILED!\n\n" + e.ToString() + "\n*/");
    }

    IncrementProgressParallel();
}

async Task DumpSprites()
{
    await Task.Run(() => Parallel.ForEach(allSprites, DumpSprite));
}

void DumpSprite(UndertaleSprite sprite)
{
    if (sprite is null)
    {
        return;
    }

    for (int i = 0; i < sprite.Textures.Count; i++)
    {
        if (sprite.Textures[i]?.Texture is not null)
        {
            UndertaleTexturePageItem tex = sprite.Textures[i].Texture;
            string sprFolder2 = Path.Combine(sprFolder, sprite.Name.Content);
            Directory.CreateDirectory(sprFolder2);
            worker.ExportAsPNG(tex, Path.Combine(sprFolder2, $"{sprite.Name.Content}_{i}.png"));
        }
    }

    AddProgressParallel(sprite.Textures.Count);
}

async Task DumpBackgrounds()
{
    await Task.Run(() => Parallel.ForEach(allBackgrounds, DumpBackground));
}

void DumpBackground(UndertaleBackground background)
{
    if (background?.Texture is null)
    {
        return;
    }

    UndertaleTexturePageItem tex = background.Texture;
    string bgrFolder2 = Path.Combine(bgrFolder, background.Name.Content);
    Directory.CreateDirectory(bgrFolder2);
    worker.ExportAsPNG(tex, Path.Combine(bgrFolder2, $"{background.Name.Content}_0.png"));
    IncrementProgressParallel();
}

async Task DumpFonts()
{
    await Task.Run(() => Parallel.ForEach(allFonts, DumpFont));
}

void DumpFont(UndertaleFont font)
{
    if (font?.Texture is null)
    {
        return;
    }

    try
    {
        string name = SafeName(font.Name.Content);
        if (font.Texture != null)
        {
            string png = Path.Combine(fntFolder, name + ".png");
            worker.ExportAsPNG(font.Texture, png);
        }

        string csv = Path.Combine(fntFolder, $"glyphs_{name}.csv");
        using (var writer = new StreamWriter(csv, false, Encoding.UTF8))
        {
            writer.WriteLine($"{font.DisplayName?.Content ?? ""};{font.EmSize};{font.Bold};{font.Italic};{font.Charset};{font.AntiAliasing};{font.ScaleX};{font.ScaleY}");

            foreach (var g in font.Glyphs)
            {
                writer.WriteLine($"{g.Character};{g.SourceX};{g.SourceY};{g.SourceWidth};{g.SourceHeight};{g.Shift};{g.Offset}");
            }
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export font {font.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}


async Task DumpShaders()
{
    await Task.Run(() => Parallel.ForEach(allShaders, DumpShader));
}

void DumpShader(UndertaleShader shader)
{
    if (shader?.Name?.Content == null) return;

    string shaderDir = Path.Combine(shadersOut, SafeName(shader.Name.Content));
    ExportShader(shader, shaderDir);
    IncrementProgressParallel();
}

async Task DumpSounds()
{
    await Task.Run(() => Parallel.ForEach(allSounds, DumpSound));
}

void DumpSound(UndertaleSound sound)
{
    if (sound?.Name?.Content == null) return;

    try
    {
        string name = SafeName(sound.Name.Content);

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
            byte[] soundData = GetSoundData(sound, Data, comparisonPath);
            string soundFile = Path.Combine(soundsOut, name + audioExt);
            File.WriteAllBytes(soundFile, soundData);
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export sound {sound.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

async Task DumpTilesets()
{
    await Task.Run(() => Parallel.ForEach(allBackgrounds, DumpTileset));
}

void DumpTileset(UndertaleBackground bg)
{
    if (bg?.Name?.Content == null) return;

    string name = SafeName(bg.Name.Content);

    if (bg?.Texture == null)
    {
        return;
    }

    try
    {
        string png = Path.Combine(bgrFolder, name + ".png");
        worker.ExportAsPNG(bg.Texture, png);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export tileset {name}: {ex.Message}");
    }

    IncrementProgressParallel();
}

async Task DumpRooms()
{
    await Task.Run(() => Parallel.ForEach(allRooms, DumpRoom));
}

void DumpRoom(UndertaleRoom room)
{
    if (room?.Name?.Content == null) return;

    try
    {
        string name = SafeName(room.Name.Content);
        string jsonPath = Path.Combine(roomsOut, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();

            writer.WriteString("name", room.Name.Content);
            writer.WriteString("caption", room.Caption?.Content ?? "");
            writer.WriteNumber("width", (int)room.Width);
            writer.WriteNumber("height", (int)room.Height);
            writer.WriteNumber("speed", (int)room.Speed);
            writer.WriteBoolean("persistent", room.Persistent);
            writer.WriteNumber("backgroundColor", (int)room.BackgroundColor);
            writer.WriteBoolean("drawBackgroundColor", room.DrawBackgroundColor);
            writer.WriteString("creationCodeId", room.CreationCodeId?.Name?.Content ?? "");
            writer.WriteNumber("flags", (int)room.Flags);
            writer.WriteBoolean("world", room.World);
            writer.WriteNumber("top", (int)room.Top);
            writer.WriteNumber("left", (int)room.Left);
            writer.WriteNumber("right", (int)room.Right);
            writer.WriteNumber("bottom", (int)room.Bottom);
            writer.WriteNumber("gravityX", room.GravityX);
            writer.WriteNumber("gravityY", room.GravityY);
            writer.WriteNumber("metersPerPixel", room.MetersPerPixel);
            writer.WriteNumber("gridWidth", (float)room.GridWidth);
            writer.WriteNumber("gridHeight", (float)room.GridHeight);
            writer.WriteNumber("gridThicknessPx", (float)room.GridThicknessPx);

            writer.WriteStartArray("backgrounds");
            foreach (var bg in room.Backgrounds)
            {
                writer.WriteStartObject();
                writer.WriteBoolean("enabled", bg.Enabled);
                writer.WriteBoolean("foreground", bg.Foreground);
                writer.WriteString("backgroundDefinition", bg.BackgroundDefinition?.Name?.Content ?? "");
                writer.WriteNumber("x", bg.X);
                writer.WriteNumber("y", bg.Y);
                writer.WriteBoolean("tiledHorizontally", bg.TiledHorizontally);
                writer.WriteBoolean("tiledVertically", bg.TiledVertically);
                writer.WriteNumber("speedX", bg.SpeedX);
                writer.WriteNumber("speedY", bg.SpeedY);
                writer.WriteBoolean("stretch", bg.Stretch);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteStartArray("views");
            foreach (var view in room.Views)
            {
                writer.WriteStartObject();
                writer.WriteBoolean("enabled", view.Enabled);
                writer.WriteNumber("viewX", view.ViewX);
                writer.WriteNumber("viewY", view.ViewY);
                writer.WriteNumber("viewWidth", view.ViewWidth);
                writer.WriteNumber("viewHeight", view.ViewHeight);
                writer.WriteNumber("portX", view.PortX);
                writer.WriteNumber("portY", view.PortY);
                writer.WriteNumber("portWidth", view.PortWidth);
                writer.WriteNumber("portHeight", view.PortHeight);
                writer.WriteNumber("borderX", (int)view.BorderX);
                writer.WriteNumber("borderY", (int)view.BorderY);
                writer.WriteNumber("speedX", view.SpeedX);
                writer.WriteNumber("speedY", view.SpeedY);
                writer.WriteString("objectId", view.ObjectId?.Name?.Content ?? "");
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteStartArray("gameObjects");
            foreach (var obj in room.GameObjects)
            {
                writer.WriteStartObject();
                writer.WriteNumber("x", obj.X);
                writer.WriteNumber("y", obj.Y);
                writer.WriteString("objectDefinition", obj.ObjectDefinition?.Name?.Content ?? "");
                writer.WriteNumber("instanceID", (int)obj.InstanceID);
                writer.WriteString("creationCode", obj.CreationCode?.Name?.Content ?? "");
                writer.WriteNumber("scaleX", obj.ScaleX);
                writer.WriteNumber("scaleY", obj.ScaleY);
                writer.WriteNumber("color", (int)obj.Color);
                writer.WriteNumber("rotation", obj.Rotation);
                writer.WriteString("preCreateCode", obj.PreCreateCode?.Name?.Content ?? "");
                if (Data.IsVersionAtLeast(2, 2, 2, 302))
                {
                    writer.WriteNumber("imageSpeed", obj.ImageSpeed);
                    writer.WriteNumber("imageIndex", obj.ImageIndex);
                }
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteStartArray("tiles");
            foreach (var tile in room.Tiles)
            {
                writer.WriteStartObject();
                writer.WriteNumber("x", tile.X);
                writer.WriteNumber("y", tile.Y);
                writer.WriteBoolean("spriteMode", tile.spriteMode);
                if (tile.spriteMode)
                {
                    writer.WriteString("spriteDefinition", tile.SpriteDefinition?.Name?.Content ?? "");
                }
                else
                {
                    writer.WriteString("backgroundDefinition", tile.BackgroundDefinition?.Name?.Content ?? "");
                }
                writer.WriteNumber("sourceX", tile.SourceX);
                writer.WriteNumber("sourceY", tile.SourceY);
                writer.WriteNumber("width", (int)tile.Width);
                writer.WriteNumber("height", (int)tile.Height);
                writer.WriteNumber("tileDepth", tile.TileDepth);
                writer.WriteNumber("instanceID", (int)tile.InstanceID);
                writer.WriteNumber("scaleX", tile.ScaleX);
                writer.WriteNumber("scaleY", tile.ScaleY);
                writer.WriteNumber("color", (int)tile.Color);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();


            if (Data.IsGameMaker2() && room.Layers != null && room.Layers.Count > 0)
            {
                writer.WriteStartArray("layers");
                foreach (var layer in room.Layers)
                {
                    writer.WriteStartObject();
                    writer.WriteString("layerName", layer.LayerName?.Content ?? "");
                    writer.WriteNumber("layerId", (int)layer.LayerId);
                    writer.WriteNumber("layerType", (int)layer.LayerType);
                    writer.WriteNumber("layerDepth", layer.LayerDepth);
                    writer.WriteNumber("xOffset", layer.XOffset);
                    writer.WriteNumber("yOffset", layer.YOffset);
                    writer.WriteNumber("hSpeed", layer.HSpeed);
                    writer.WriteNumber("vSpeed", layer.VSpeed);
                    writer.WriteBoolean("isVisible", layer.IsVisible);
                    if (Data.IsVersionAtLeast(2022, 1))
                    {
                        writer.WriteBoolean("effectEnabled", layer.EffectEnabled);
                        writer.WriteString("effectType", layer.EffectType?.Content ?? "");
                    }

                    if (layer.LayerType == UndertaleRoom.LayerType.Instances && layer.InstancesData != null)
                    {
                        writer.WriteStartArray("instanceIds");
                        if (layer.InstancesData.Instances != null)
                        {
                            foreach (var inst in layer.InstancesData.Instances)
                            {
                                writer.WriteNumberValue((int)inst.InstanceID);
                            }
                        }
                        writer.WriteEndArray();
                    }
                    else if (layer.LayerType == UndertaleRoom.LayerType.Tiles && layer.TilesData != null)
                    {
                        var tilesData = layer.TilesData;
                        writer.WriteString("tilesBackground", tilesData.Background?.Name?.Content ?? "");
                        writer.WriteNumber("tilesX", (int)tilesData.TilesX);
                        writer.WriteNumber("tilesY", (int)tilesData.TilesY);
                        writer.WriteStartArray("tileData");
                        if (tilesData.TileData != null)
                        {
                            foreach (var row in tilesData.TileData)
                            {
                                writer.WriteStartArray();
                                if (row != null)
                                {
                                    foreach (var value in row)
                                    {
                                        writer.WriteNumberValue(value);
                                    }
                                }
                                writer.WriteEndArray();
                            }
                        }
                        writer.WriteEndArray();
                    }
                    else if (layer.LayerType == UndertaleRoom.LayerType.Background && layer.BackgroundData != null)
                    {
                        var bgData = layer.BackgroundData;
                        writer.WriteStartObject("backgroundData");
                        writer.WriteBoolean("visible", bgData.Visible);
                        writer.WriteBoolean("foreground", bgData.Foreground);
                        writer.WriteString("sprite", bgData.Sprite?.Name?.Content ?? "");
                        writer.WriteBoolean("tiledHorizontally", bgData.TiledHorizontally);
                        writer.WriteBoolean("tiledVertically", bgData.TiledVertically);
                        writer.WriteBoolean("stretch", bgData.Stretch);
                        writer.WriteNumber("color", (int)bgData.Color);
                        writer.WriteNumber("firstFrame", bgData.FirstFrame);
                        writer.WriteNumber("animationSpeed", bgData.AnimationSpeed);
                        writer.WriteNumber("animationSpeedType", (int)bgData.AnimationSpeedType);
                        writer.WriteEndObject();
                    }
                    else if (layer.LayerType == UndertaleRoom.LayerType.Assets && layer.AssetsData != null)
                    {
                        var assetsData = layer.AssetsData;
                        writer.WriteStartObject("assetsData");

                        writer.WriteStartArray("legacyTiles");
                        if (assetsData.LegacyTiles != null)
                        {
                            foreach (var tile in assetsData.LegacyTiles)
                            {
                                writer.WriteStartObject();
                                writer.WriteNumber("x", tile.X);
                                writer.WriteNumber("y", tile.Y);
                                writer.WriteNumber("sourceX", (int)tile.SourceX);
                                writer.WriteNumber("sourceY", (int)tile.SourceY);
                                writer.WriteNumber("width", (int)tile.Width);
                                writer.WriteNumber("height", (int)tile.Height);
                                writer.WriteNumber("tileDepth", tile.TileDepth);
                                writer.WriteNumber("instanceID", (int)tile.InstanceID);
                                writer.WriteNumber("scaleX", tile.ScaleX);
                                writer.WriteNumber("scaleY", tile.ScaleY);
                                writer.WriteNumber("color", (int)tile.Color);
                                writer.WriteString("background", tile.BackgroundDefinition?.Name?.Content ?? "");
                                writer.WriteEndObject();
                            }
                        }
                        writer.WriteEndArray();

                        writer.WriteStartArray("sprites");
                        if (assetsData.Sprites != null)
                        {
                            foreach (var spr in assetsData.Sprites)
                            {
                                writer.WriteStartObject();
                                writer.WriteString("name", spr.Name?.Content ?? "");
                                writer.WriteString("sprite", spr.Sprite?.Name?.Content ?? "");
                                writer.WriteNumber("x", spr.X);
                                writer.WriteNumber("y", spr.Y);
                                writer.WriteNumber("scaleX", spr.ScaleX);
                                writer.WriteNumber("scaleY", spr.ScaleY);
                                writer.WriteNumber("color", (int)spr.Color);
                                writer.WriteNumber("animationSpeed", spr.AnimationSpeed);
                                writer.WriteNumber("animationSpeedType", (int)spr.AnimationSpeedType);
                                writer.WriteNumber("frameIndex", spr.FrameIndex);
                                writer.WriteNumber("rotation", spr.Rotation);
                                writer.WriteEndObject();
                            }
                        }
                        writer.WriteEndArray();

                        writer.WriteEndObject();
                    }

                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
            }


            if (Data.IsVersionAtLeast(2, 3) && room.Sequences != null && room.Sequences.Count > 0)
            {
                writer.WriteStartArray("sequences");
                foreach (var seq in room.Sequences)
                {
                    writer.WriteStringValue(seq?.Resource?.Name?.Content ?? "");
                }
                writer.WriteEndArray();
            }

            if (Data.IsVersionAtLeast(2024, 13) && room.InstanceCreationOrderIDs != null && room.InstanceCreationOrderIDs.InstanceIDs != null && room.InstanceCreationOrderIDs.InstanceIDs.Count > 0)
            {
                writer.WriteStartArray("instanceCreationOrderIDs");
                foreach (var id in room.InstanceCreationOrderIDs.InstanceIDs)
                {
                    writer.WriteNumberValue(id);
                }
                writer.WriteEndArray();
            }

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export room {room.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

async Task DumpAudioGroups()
{
    await Task.Run(() => Parallel.ForEach(allAudioGroups, DumpAudioGroup));
}

void DumpAudioGroup(UndertaleAudioGroup audioGroup)
{
    if (audioGroup?.Name?.Content == null) return;

    try
    {
        string name = SafeName(audioGroup.Name.Content);
        string jsonPath = Path.Combine(audioGroupsOut, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", audioGroup.Name.Content);
            if (audioGroup.Path != null)
            {
                writer.WriteString("path", audioGroup.Path.Content ?? "");
            }
            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export audio group {audioGroup.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

async Task DumpPaths()
{
    await Task.Run(() => Parallel.ForEach(allPaths, DumpPath));
}

void DumpPath(UndertalePath path)
{
    if (path?.Name?.Content == null) return;

    try
    {
        string name = SafeName(path.Name.Content);
        string jsonPath = Path.Combine(pathsOut, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", path.Name.Content);
            writer.WriteBoolean("isSmooth", path.IsSmooth);
            writer.WriteBoolean("isClosed", path.IsClosed);
            writer.WriteNumber("precision", (int)path.Precision);

            writer.WriteStartArray("points");
            foreach (var point in path.Points)
            {
                writer.WriteStartObject();
                writer.WriteNumber("x", point.X);
                writer.WriteNumber("y", point.Y);
                writer.WriteNumber("speed", point.Speed);
                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export path {path.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

async Task DumpTimelines()
{
    await Task.Run(() => Parallel.ForEach(allTimelines, DumpTimeline));
}

void DumpTimeline(UndertaleTimeline timeline)
{
    if (timeline?.Name?.Content == null) return;

    try
    {
        string name = SafeName(timeline.Name.Content);
        string jsonPath = Path.Combine(timelinesOut, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", timeline.Name.Content);

            writer.WriteStartArray("moments");
            foreach (var moment in timeline.Moments)
            {
                writer.WriteStartObject();
                writer.WriteNumber("step", (int)moment.Step);

                if (moment.Event != null && moment.Event.Count > 0)
                {
                    writer.WriteStartArray("actions");
                    foreach (var action in moment.Event)
                    {
                        writer.WriteStartObject();
                        if (action.CodeId != null && action.CodeId.Name != null)
                        {
                            writer.WriteString("codeId", action.CodeId.Name.Content ?? "");
                        }
                        else
                        {
                            writer.WriteNull("codeId");
                        }
                        writer.WriteEndObject();
                    }
                    writer.WriteEndArray();
                }

                writer.WriteEndObject();
            }
            writer.WriteEndArray();

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export timeline {timeline.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

async Task DumpExtensions()
{
    await Task.Run(() => Parallel.ForEach(allExtensions, DumpExtension));
}

void DumpExtension(UndertaleExtension extension)
{
    if (extension?.Name?.Content == null) return;

    try
    {
        string name = SafeName(extension.Name.Content);
        string jsonPath = Path.Combine(extensionsOut, name + ".json");

        using (var stream = new FileStream(jsonPath, FileMode.Create, FileAccess.Write))
        using (var writer = new Utf8JsonWriter(stream, new JsonWriterOptions { Indented = true }))
        {
            writer.WriteStartObject();
            writer.WriteString("name", extension.Name.Content);
            writer.WriteString("folderName", extension.FolderName?.Content ?? "");
            if (extension.Version != null)
            {
                writer.WriteString("version", extension.Version.Content ?? "");
            }
            if (extension.ClassName != null)
            {
                writer.WriteString("className", extension.ClassName.Content ?? "");
            }

            if (extension.Files != null && extension.Files.Count > 0)
            {
                writer.WriteStartArray("files");
                foreach (var file in extension.Files)
                {
                    writer.WriteStartObject();
                    writer.WriteString("filename", file.Filename?.Content ?? "");
                    writer.WriteNumber("kind", (int)file.Kind);
                    if (file.InitScript != null)
                    {
                        writer.WriteString("initScript", file.InitScript.Content ?? "");
                    }
                    if (file.CleanupScript != null)
                    {
                        writer.WriteString("cleanupScript", file.CleanupScript.Content ?? "");
                    }

                    writer.WriteStartArray("functions");
                    if (file.Functions != null)
                    {
                        foreach (var func in file.Functions)
                        {
                            writer.WriteStartObject();
                            writer.WriteString("name", func.Name?.Content ?? "");
                            if (func.ExtName != null)
                            {
                                writer.WriteString("extName", func.ExtName.Content ?? "");
                            }
                            writer.WriteNumber("id", (int)func.ID);
                            writer.WriteNumber("kind", (int)func.Kind);
                            writer.WriteNumber("retType", (int)func.RetType);

                            writer.WriteStartArray("arguments");
                            if (func.Arguments != null)
                            {
                                foreach (var arg in func.Arguments)
                                {
                                    writer.WriteStartObject();
                                    writer.WriteNumber("type", (int)arg.Type);
                                    writer.WriteEndObject();
                                }
                            }
                            writer.WriteEndArray();

                            writer.WriteEndObject();
                        }
                    }
                    writer.WriteEndArray();

                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
            }

            if (extension.Options != null && extension.Options.Count > 0)
            {
                writer.WriteStartArray("options");
                foreach (var option in extension.Options)
                {
                    writer.WriteStartObject();
                    writer.WriteString("name", option.Name?.Content ?? "");
                    writer.WriteString("value", option.Value?.Content ?? "");
                    writer.WriteEndObject();
                }
                writer.WriteEndArray();
            }

            writer.WriteEndObject();
        }
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export extension {extension.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

PrintLine($"\n[ExportAllAssets] Summary for Mod {modNo}:");
PrintLine($"  Code - Exported: {allCode.Count}");
PrintLine($"  Sprites - Exported: {allSprites.Count}");
PrintLine($"  Backgrounds - Exported: {allBackgrounds.Count}");
PrintLine($"  Fonts - Exported: {allFonts.Count}");
PrintLine($"  Shaders - Exported: {allShaders.Count}");
PrintLine($"  Sounds - Exported: {allSounds.Count}");
PrintLine($"  Rooms - Exported: {allRooms.Count}");
PrintLine($"  AudioGroups - Exported: {allAudioGroups.Count}");
PrintLine($"  Paths - Exported: {allPaths.Count}");
PrintLine($"  Timelines - Exported: {allTimelines.Count}");
PrintLine($"  Extensions - Exported: {allExtensions.Count}");
PrintLine("[ExportAllAssets] Done.");

