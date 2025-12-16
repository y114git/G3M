#load "SharedPaths.csx"

using System.Text;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
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

Directory.CreateDirectory(codeFolder);
Directory.CreateDirectory(sprFolder);
Directory.CreateDirectory(fntFolder);
Directory.CreateDirectory(bgrFolder);
Directory.CreateDirectory(shadersOut);
Directory.CreateDirectory(soundsOut);
Directory.CreateDirectory(roomsOut);

PrintLine($"[ExportAllAssets] Starting full export for mod {modNo}...");

GlobalDecompileContext globalDecompileContext = new(Data);
Underanalyzer.Decompiler.IDecompileSettings decompilerSettings = Data.ToolInfo.DecompilerSettings;

void WriteJsonString(StringBuilder sb, string value)
{
    if (value == null) { sb.Append("null"); return; }
    sb.Append("\"");
    foreach (var ch in value)
    {
        if (ch == '"') sb.Append("\\\"");
        else if (ch == '\\') sb.Append("\\\\");
        else if (ch == '\n') sb.Append("\\n");
        else if (ch == '\r') sb.Append("\\r");
        else if (ch == '\t') sb.Append("\\t");
        else sb.Append(ch);
    }
    sb.Append("\"");
}

void WriteJsonBool(StringBuilder sb, bool value) => sb.Append(value ? "true" : "false");
void WriteJsonNumber(StringBuilder sb, int value) => sb.Append(value);
void WriteJsonNumber(StringBuilder sb, uint value) => sb.Append(value);
void WriteJsonNumber(StringBuilder sb, float value) => sb.Append(value.ToString("G9"));
void WriteJsonNumber(StringBuilder sb, double value) => sb.Append(value.ToString("G9"));

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

int totalItems = allCode.Count + allSprites.Count + allBackgrounds.Count + allFonts.Count + allShaders.Count + allSounds.Count + allRooms.Count;

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

        var json = new StringBuilder();
        json.Append("{\n");


        WriteJsonString(json, "name"); json.Append(": "); WriteJsonString(json, room.Name.Content); json.Append(",\n");
        WriteJsonString(json, "caption"); json.Append(": "); WriteJsonString(json, room.Caption?.Content ?? ""); json.Append(",\n");
        WriteJsonString(json, "width"); json.Append(": "); WriteJsonNumber(json, (int)room.Width); json.Append(",\n");
        WriteJsonString(json, "height"); json.Append(": "); WriteJsonNumber(json, (int)room.Height); json.Append(",\n");
        WriteJsonString(json, "speed"); json.Append(": "); WriteJsonNumber(json, (int)room.Speed); json.Append(",\n");
        WriteJsonString(json, "persistent"); json.Append(": "); WriteJsonBool(json, room.Persistent); json.Append(",\n");
        WriteJsonString(json, "backgroundColor"); json.Append(": "); WriteJsonNumber(json, (int)room.BackgroundColor); json.Append(",\n");
        WriteJsonString(json, "drawBackgroundColor"); json.Append(": "); WriteJsonBool(json, room.DrawBackgroundColor); json.Append(",\n");
        WriteJsonString(json, "creationCodeId"); json.Append(": "); WriteJsonString(json, room.CreationCodeId?.Name?.Content ?? ""); json.Append(",\n");
        WriteJsonString(json, "flags"); json.Append(": "); WriteJsonNumber(json, (int)room.Flags); json.Append(",\n");
        WriteJsonString(json, "world"); json.Append(": "); WriteJsonBool(json, room.World); json.Append(",\n");
        WriteJsonString(json, "top"); json.Append(": "); WriteJsonNumber(json, (int)room.Top); json.Append(",\n");
        WriteJsonString(json, "left"); json.Append(": "); WriteJsonNumber(json, (int)room.Left); json.Append(",\n");
        WriteJsonString(json, "right"); json.Append(": "); WriteJsonNumber(json, (int)room.Right); json.Append(",\n");
        WriteJsonString(json, "bottom"); json.Append(": "); WriteJsonNumber(json, (int)room.Bottom); json.Append(",\n");
        WriteJsonString(json, "gravityX"); json.Append(": "); WriteJsonNumber(json, room.GravityX); json.Append(",\n");
        WriteJsonString(json, "gravityY"); json.Append(": "); WriteJsonNumber(json, room.GravityY); json.Append(",\n");
        WriteJsonString(json, "metersPerPixel"); json.Append(": "); WriteJsonNumber(json, room.MetersPerPixel); json.Append(",\n");
        WriteJsonString(json, "gridWidth"); json.Append(": "); WriteJsonNumber(json, (float)room.GridWidth); json.Append(",\n");
        WriteJsonString(json, "gridHeight"); json.Append(": "); WriteJsonNumber(json, (float)room.GridHeight); json.Append(",\n");
        WriteJsonString(json, "gridThicknessPx"); json.Append(": "); WriteJsonNumber(json, (float)room.GridThicknessPx); json.Append(",\n");


        json.Append("  \"backgrounds\": [\n");
        for (int i = 0; i < room.Backgrounds.Count; i++)
        {
            var bg = room.Backgrounds[i];
            json.Append("    {\n");
            WriteJsonString(json, "enabled"); json.Append(": "); WriteJsonBool(json, bg.Enabled); json.Append(",\n");
            WriteJsonString(json, "foreground"); json.Append(": "); WriteJsonBool(json, bg.Foreground); json.Append(",\n");
            WriteJsonString(json, "backgroundDefinition"); json.Append(": "); WriteJsonString(json, bg.BackgroundDefinition?.Name?.Content ?? ""); json.Append(",\n");
            WriteJsonString(json, "x"); json.Append(": "); WriteJsonNumber(json, bg.X); json.Append(",\n");
            WriteJsonString(json, "y"); json.Append(": "); WriteJsonNumber(json, bg.Y); json.Append(",\n");
            WriteJsonString(json, "tiledHorizontally"); json.Append(": "); WriteJsonBool(json, bg.TiledHorizontally); json.Append(",\n");
            WriteJsonString(json, "tiledVertically"); json.Append(": "); WriteJsonBool(json, bg.TiledVertically); json.Append(",\n");
            WriteJsonString(json, "speedX"); json.Append(": "); WriteJsonNumber(json, bg.SpeedX); json.Append(",\n");
            WriteJsonString(json, "speedY"); json.Append(": "); WriteJsonNumber(json, bg.SpeedY); json.Append(",\n");
            WriteJsonString(json, "stretch"); json.Append(": "); WriteJsonBool(json, bg.Stretch);
            json.Append("\n    }");
            if (i < room.Backgrounds.Count - 1) json.Append(",");
            json.Append("\n");
        }
        json.Append("  ],\n");


        json.Append("  \"views\": [\n");
        for (int i = 0; i < room.Views.Count; i++)
        {
            var view = room.Views[i];
            json.Append("    {\n");
            WriteJsonString(json, "enabled"); json.Append(": "); WriteJsonBool(json, view.Enabled); json.Append(",\n");
            WriteJsonString(json, "viewX"); json.Append(": "); WriteJsonNumber(json, view.ViewX); json.Append(",\n");
            WriteJsonString(json, "viewY"); json.Append(": "); WriteJsonNumber(json, view.ViewY); json.Append(",\n");
            WriteJsonString(json, "viewWidth"); json.Append(": "); WriteJsonNumber(json, view.ViewWidth); json.Append(",\n");
            WriteJsonString(json, "viewHeight"); json.Append(": "); WriteJsonNumber(json, view.ViewHeight); json.Append(",\n");
            WriteJsonString(json, "portX"); json.Append(": "); WriteJsonNumber(json, view.PortX); json.Append(",\n");
            WriteJsonString(json, "portY"); json.Append(": "); WriteJsonNumber(json, view.PortY); json.Append(",\n");
            WriteJsonString(json, "portWidth"); json.Append(": "); WriteJsonNumber(json, view.PortWidth); json.Append(",\n");
            WriteJsonString(json, "portHeight"); json.Append(": "); WriteJsonNumber(json, view.PortHeight); json.Append(",\n");
            WriteJsonString(json, "borderX"); json.Append(": "); WriteJsonNumber(json, (int)view.BorderX); json.Append(",\n");
            WriteJsonString(json, "borderY"); json.Append(": "); WriteJsonNumber(json, (int)view.BorderY); json.Append(",\n");
            WriteJsonString(json, "speedX"); json.Append(": "); WriteJsonNumber(json, view.SpeedX); json.Append(",\n");
            WriteJsonString(json, "speedY"); json.Append(": "); WriteJsonNumber(json, view.SpeedY); json.Append(",\n");
            WriteJsonString(json, "objectId"); json.Append(": "); WriteJsonString(json, view.ObjectId?.Name?.Content ?? "");
            json.Append("\n    }");
            if (i < room.Views.Count - 1) json.Append(",");
            json.Append("\n");
        }
        json.Append("  ],\n");


        json.Append("  \"gameObjects\": [\n");
        for (int i = 0; i < room.GameObjects.Count; i++)
        {
            var obj = room.GameObjects[i];
            json.Append("    {\n");
            WriteJsonString(json, "x"); json.Append(": "); WriteJsonNumber(json, obj.X); json.Append(",\n");
            WriteJsonString(json, "y"); json.Append(": "); WriteJsonNumber(json, obj.Y); json.Append(",\n");
            WriteJsonString(json, "objectDefinition"); json.Append(": "); WriteJsonString(json, obj.ObjectDefinition?.Name?.Content ?? ""); json.Append(",\n");
            WriteJsonString(json, "instanceID"); json.Append(": "); WriteJsonNumber(json, (int)obj.InstanceID); json.Append(",\n");
            WriteJsonString(json, "creationCode"); json.Append(": "); WriteJsonString(json, obj.CreationCode?.Name?.Content ?? ""); json.Append(",\n");
            WriteJsonString(json, "scaleX"); json.Append(": "); WriteJsonNumber(json, obj.ScaleX); json.Append(",\n");
            WriteJsonString(json, "scaleY"); json.Append(": "); WriteJsonNumber(json, obj.ScaleY); json.Append(",\n");
            WriteJsonString(json, "color"); json.Append(": "); WriteJsonNumber(json, (int)obj.Color); json.Append(",\n");
            WriteJsonString(json, "rotation"); json.Append(": "); WriteJsonNumber(json, obj.Rotation); json.Append(",\n");
            WriteJsonString(json, "preCreateCode"); json.Append(": "); WriteJsonString(json, obj.PreCreateCode?.Name?.Content ?? "");
            if (Data.IsVersionAtLeast(2, 2, 2, 302))
            {
                json.Append(",\n");
                WriteJsonString(json, "imageSpeed"); json.Append(": "); WriteJsonNumber(json, obj.ImageSpeed); json.Append(",\n");
                WriteJsonString(json, "imageIndex"); json.Append(": "); WriteJsonNumber(json, obj.ImageIndex);
            }
            json.Append("\n    }");
            if (i < room.GameObjects.Count - 1) json.Append(",");
            json.Append("\n");
        }
        json.Append("  ],\n");


        json.Append("  \"tiles\": [\n");
        for (int i = 0; i < room.Tiles.Count; i++)
        {
            var tile = room.Tiles[i];
            json.Append("    {\n");
            WriteJsonString(json, "x"); json.Append(": "); WriteJsonNumber(json, tile.X); json.Append(",\n");
            WriteJsonString(json, "y"); json.Append(": "); WriteJsonNumber(json, tile.Y); json.Append(",\n");
            WriteJsonString(json, "spriteMode"); json.Append(": "); WriteJsonBool(json, tile.spriteMode); json.Append(",\n");
            if (tile.spriteMode)
            {
                WriteJsonString(json, "spriteDefinition"); json.Append(": "); WriteJsonString(json, tile.SpriteDefinition?.Name?.Content ?? ""); json.Append(",\n");
            }
            else
            {
                WriteJsonString(json, "backgroundDefinition"); json.Append(": "); WriteJsonString(json, tile.BackgroundDefinition?.Name?.Content ?? ""); json.Append(",\n");
            }
            WriteJsonString(json, "sourceX"); json.Append(": "); WriteJsonNumber(json, tile.SourceX); json.Append(",\n");
            WriteJsonString(json, "sourceY"); json.Append(": "); WriteJsonNumber(json, tile.SourceY); json.Append(",\n");
            WriteJsonString(json, "width"); json.Append(": "); WriteJsonNumber(json, (int)tile.Width); json.Append(",\n");
            WriteJsonString(json, "height"); json.Append(": "); WriteJsonNumber(json, (int)tile.Height); json.Append(",\n");
            WriteJsonString(json, "tileDepth"); json.Append(": "); WriteJsonNumber(json, tile.TileDepth); json.Append(",\n");
            WriteJsonString(json, "instanceID"); json.Append(": "); WriteJsonNumber(json, (int)tile.InstanceID); json.Append(",\n");
            WriteJsonString(json, "scaleX"); json.Append(": "); WriteJsonNumber(json, tile.ScaleX); json.Append(",\n");
            WriteJsonString(json, "scaleY"); json.Append(": "); WriteJsonNumber(json, tile.ScaleY); json.Append(",\n");
            WriteJsonString(json, "color"); json.Append(": "); WriteJsonNumber(json, (int)tile.Color);
            json.Append("\n    }");
            if (i < room.Tiles.Count - 1) json.Append(",");
            json.Append("\n");
        }
        json.Append("  ]");


        if (Data.IsGameMaker2() && room.Layers != null && room.Layers.Count > 0)
        {
            json.Append(",\n  \"layers\": [\n");
            for (int i = 0; i < room.Layers.Count; i++)
            {
                var layer = room.Layers[i];
                json.Append("    {\n");
                WriteJsonString(json, "layerName"); json.Append(": "); WriteJsonString(json, layer.LayerName?.Content ?? ""); json.Append(",\n");
                WriteJsonString(json, "layerId"); json.Append(": "); WriteJsonNumber(json, (int)layer.LayerId); json.Append(",\n");
                WriteJsonString(json, "layerType"); json.Append(": "); WriteJsonNumber(json, (int)layer.LayerType); json.Append(",\n");
                WriteJsonString(json, "layerDepth"); json.Append(": "); WriteJsonNumber(json, layer.LayerDepth); json.Append(",\n");
                WriteJsonString(json, "xOffset"); json.Append(": "); WriteJsonNumber(json, layer.XOffset); json.Append(",\n");
                WriteJsonString(json, "yOffset"); json.Append(": "); WriteJsonNumber(json, layer.YOffset); json.Append(",\n");
                WriteJsonString(json, "hSpeed"); json.Append(": "); WriteJsonNumber(json, layer.HSpeed); json.Append(",\n");
                WriteJsonString(json, "vSpeed"); json.Append(": "); WriteJsonNumber(json, layer.VSpeed); json.Append(",\n");
                WriteJsonString(json, "isVisible"); json.Append(": "); WriteJsonBool(json, layer.IsVisible);
                if (Data.IsVersionAtLeast(2022, 1))
                {
                    json.Append(",\n");
                    WriteJsonString(json, "effectEnabled"); json.Append(": "); WriteJsonBool(json, layer.EffectEnabled); json.Append(",\n");
                    WriteJsonString(json, "effectType"); json.Append(": "); WriteJsonString(json, layer.EffectType?.Content ?? "");
                }


                if (layer.LayerType == UndertaleRoom.LayerType.Instances && layer.InstancesData != null)
                {
                    json.Append(",\n");
                    json.Append("      \"instanceIds\": [\n");
                    if (layer.InstancesData.Instances != null)
                    {
                        for (int j = 0; j < layer.InstancesData.Instances.Count; j++)
                        {
                            var inst = layer.InstancesData.Instances[j];
                            json.Append("        ");
                            WriteJsonNumber(json, (int)inst.InstanceID);
                            if (j < layer.InstancesData.Instances.Count - 1) json.Append(",");
                            json.Append("\n");
                        }
                    }
                    json.Append("      ]");
                }
                else if (layer.LayerType == UndertaleRoom.LayerType.Tiles && layer.TilesData != null)
                {
                    var tilesData = layer.TilesData;
                    json.Append(",\n");
                    WriteJsonString(json, "tilesBackground"); json.Append(": "); WriteJsonString(json, tilesData.Background?.Name?.Content ?? ""); json.Append(",\n");
                    WriteJsonString(json, "tilesX"); json.Append(": "); WriteJsonNumber(json, (int)tilesData.TilesX); json.Append(",\n");
                    WriteJsonString(json, "tilesY"); json.Append(": "); WriteJsonNumber(json, (int)tilesData.TilesY); json.Append(",\n");
                    json.Append("      \"tileData\": [\n");
                    if (tilesData.TileData != null)
                    {
                        for (int y = 0; y < tilesData.TileData.Length; y++)
                        {
                            json.Append("        [");
                            var row = tilesData.TileData[y];
                            if (row != null)
                            {
                                for (int x = 0; x < row.Length; x++)
                                {
                                    json.Append(row[x]);
                                    if (x < row.Length - 1) json.Append(", ");
                                }
                            }
                            json.Append("]");
                            if (y < tilesData.TileData.Length - 1) json.Append(",");
                            json.Append("\n");
                        }
                    }
                    json.Append("      ]");
                }
                else if (layer.LayerType == UndertaleRoom.LayerType.Background && layer.BackgroundData != null)
                {
                    var bgData = layer.BackgroundData;
                    json.Append(",\n");
                    json.Append("      \"backgroundData\": {\n");
                    WriteJsonString(json, "visible"); json.Append(": "); WriteJsonBool(json, bgData.Visible); json.Append(",\n");
                    WriteJsonString(json, "foreground"); json.Append(": "); WriteJsonBool(json, bgData.Foreground); json.Append(",\n");
                    WriteJsonString(json, "sprite"); json.Append(": "); WriteJsonString(json, bgData.Sprite?.Name?.Content ?? ""); json.Append(",\n");
                    WriteJsonString(json, "tiledHorizontally"); json.Append(": "); WriteJsonBool(json, bgData.TiledHorizontally); json.Append(",\n");
                    WriteJsonString(json, "tiledVertically"); json.Append(": "); WriteJsonBool(json, bgData.TiledVertically); json.Append(",\n");
                    WriteJsonString(json, "stretch"); json.Append(": "); WriteJsonBool(json, bgData.Stretch); json.Append(",\n");
                    WriteJsonString(json, "color"); json.Append(": "); WriteJsonNumber(json, (int)bgData.Color); json.Append(",\n");
                    WriteJsonString(json, "firstFrame"); json.Append(": "); WriteJsonNumber(json, bgData.FirstFrame); json.Append(",\n");
                    WriteJsonString(json, "animationSpeed"); json.Append(": "); WriteJsonNumber(json, bgData.AnimationSpeed); json.Append(",\n");
                    WriteJsonString(json, "animationSpeedType"); json.Append(": "); WriteJsonNumber(json, (int)bgData.AnimationSpeedType);
                    json.Append("\n      }");
                }
                else if (layer.LayerType == UndertaleRoom.LayerType.Assets && layer.AssetsData != null)
                {
                    var assetsData = layer.AssetsData;
                    json.Append(",\n");
                    json.Append("      \"assetsData\": {\n");

                    json.Append("        \"legacyTiles\": [\n");
                    if (assetsData.LegacyTiles != null)
                    {
                        for (int j = 0; j < assetsData.LegacyTiles.Count; j++)
                        {
                            var tile = assetsData.LegacyTiles[j];
                            json.Append("          {\n");
                            WriteJsonString(json, "x"); json.Append(": "); WriteJsonNumber(json, tile.X); json.Append(",\n");
                            WriteJsonString(json, "y"); json.Append(": "); WriteJsonNumber(json, tile.Y); json.Append(",\n");
                            WriteJsonString(json, "sourceX"); json.Append(": "); WriteJsonNumber(json, (int)tile.SourceX); json.Append(",\n");
                            WriteJsonString(json, "sourceY"); json.Append(": "); WriteJsonNumber(json, (int)tile.SourceY); json.Append(",\n");
                            WriteJsonString(json, "width"); json.Append(": "); WriteJsonNumber(json, (int)tile.Width); json.Append(",\n");
                            WriteJsonString(json, "height"); json.Append(": "); WriteJsonNumber(json, (int)tile.Height); json.Append(",\n");
                            WriteJsonString(json, "tileDepth"); json.Append(": "); WriteJsonNumber(json, tile.TileDepth); json.Append(",\n");
                            WriteJsonString(json, "instanceID"); json.Append(": "); WriteJsonNumber(json, (int)tile.InstanceID); json.Append(",\n");
                            WriteJsonString(json, "scaleX"); json.Append(": "); WriteJsonNumber(json, tile.ScaleX); json.Append(",\n");
                            WriteJsonString(json, "scaleY"); json.Append(": "); WriteJsonNumber(json, tile.ScaleY); json.Append(",\n");
                            WriteJsonString(json, "color"); json.Append(": "); WriteJsonNumber(json, (int)tile.Color); json.Append(",\n");
                            WriteJsonString(json, "background"); json.Append(": "); WriteJsonString(json, tile.BackgroundDefinition?.Name?.Content ?? "");
                            json.Append("\n          }");
                            if (j < assetsData.LegacyTiles.Count - 1) json.Append(",");
                            json.Append("\n");
                        }
                    }
                    json.Append("        ],\n");

                    json.Append("        \"sprites\": [\n");
                    if (assetsData.Sprites != null)
                    {
                        for (int j = 0; j < assetsData.Sprites.Count; j++)
                        {
                            var spr = assetsData.Sprites[j];
                            json.Append("          {\n");
                            WriteJsonString(json, "name"); json.Append(": "); WriteJsonString(json, spr.Name?.Content ?? ""); json.Append(",\n");
                            WriteJsonString(json, "sprite"); json.Append(": "); WriteJsonString(json, spr.Sprite?.Name?.Content ?? ""); json.Append(",\n");
                            WriteJsonString(json, "x"); json.Append(": "); WriteJsonNumber(json, spr.X); json.Append(",\n");
                            WriteJsonString(json, "y"); json.Append(": "); WriteJsonNumber(json, spr.Y); json.Append(",\n");
                            WriteJsonString(json, "scaleX"); json.Append(": "); WriteJsonNumber(json, spr.ScaleX); json.Append(",\n");
                            WriteJsonString(json, "scaleY"); json.Append(": "); WriteJsonNumber(json, spr.ScaleY); json.Append(",\n");
                            WriteJsonString(json, "color"); json.Append(": "); WriteJsonNumber(json, (int)spr.Color); json.Append(",\n");
                            WriteJsonString(json, "animationSpeed"); json.Append(": "); WriteJsonNumber(json, spr.AnimationSpeed); json.Append(",\n");
                            WriteJsonString(json, "animationSpeedType"); json.Append(": "); WriteJsonNumber(json, (int)spr.AnimationSpeedType); json.Append(",\n");
                            WriteJsonString(json, "frameIndex"); json.Append(": "); WriteJsonNumber(json, spr.FrameIndex); json.Append(",\n");
                            WriteJsonString(json, "rotation"); json.Append(": "); WriteJsonNumber(json, spr.Rotation);
                            json.Append("\n          }");
                            if (j < assetsData.Sprites.Count - 1) json.Append(",");
                            json.Append("\n");
                        }
                    }
                    json.Append("        ]\n");
                    json.Append("      }");
                }

                json.Append("\n    }");
                if (i < room.Layers.Count - 1) json.Append(",");
                json.Append("\n");
            }
            json.Append("  ]");
        }


        if (Data.IsVersionAtLeast(2, 3) && room.Sequences != null && room.Sequences.Count > 0)
        {
            json.Append(",\n  \"sequences\": [\n");
            for (int i = 0; i < room.Sequences.Count; i++)
            {
                var seq = room.Sequences[i];
                json.Append("    ");
                WriteJsonString(json, seq?.Resource?.Name?.Content ?? "");
                if (i < room.Sequences.Count - 1) json.Append(",");
                json.Append("\n");
            }
            json.Append("  ]");
        }


        if (Data.IsVersionAtLeast(2024, 13) && room.InstanceCreationOrderIDs != null && room.InstanceCreationOrderIDs.InstanceIDs != null && room.InstanceCreationOrderIDs.InstanceIDs.Count > 0)
        {
            json.Append(",\n  \"instanceCreationOrderIDs\": [\n");
            for (int i = 0; i < room.InstanceCreationOrderIDs.InstanceIDs.Count; i++)
            {
                json.Append("    ");
                WriteJsonNumber(json, room.InstanceCreationOrderIDs.InstanceIDs[i]);
                if (i < room.InstanceCreationOrderIDs.InstanceIDs.Count - 1) json.Append(",");
                json.Append("\n");
            }
            json.Append("  ]");
        }

        json.Append("\n}");

        File.WriteAllText(jsonPath, json.ToString(), Encoding.UTF8);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportAllAssets] Failed to export room {room.Name?.Content}: {ex.Message}");
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
PrintLine("[ExportAllAssets] Done.");

