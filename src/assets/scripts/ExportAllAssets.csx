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
bool DEBUG = Environment.GetEnvironmentVariable("DELTAHUB_DEBUG") == "1";
void DebugLog(string s) { if (DEBUG) PrintLine($"[DEBUG] {s}"); }

string SafeName(string name)
{
    var invalid = Path.GetInvalidFileNameChars();
    var sb = new StringBuilder(name.Length);
    foreach (var ch in name) sb.Append(invalid.Contains(ch) ? '_' : ch);
    return sb.ToString();
}

object GetProp(object obj, string name)
    => obj?.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase)?.GetValue(obj);

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

string chapterNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));

string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
string outputRoot = Path.Combine(modRoot, "Objects");
Directory.CreateDirectory(outputRoot);

string codeFolder = Path.Combine(outputRoot, "CodeEntries");
string sprFolder = Path.Combine(outputRoot, "Sprites");
string fntFolder = Path.Combine(outputRoot, "Fonts");
string bgrFolder = Path.Combine(outputRoot, "Backgrounds");
string shadersOut = Path.Combine(outputRoot, "Shaders");
string soundsOut = Path.Combine(outputRoot, "Sounds");

Directory.CreateDirectory(codeFolder);
Directory.CreateDirectory(sprFolder);
Directory.CreateDirectory(fntFolder);
Directory.CreateDirectory(bgrFolder);
Directory.CreateDirectory(shadersOut);
Directory.CreateDirectory(soundsOut);

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
    comparisonPath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, "0", "data.win");
}


List<UndertaleCode> allCode = Data.Code.Where(c => c.ParentEntry is null).ToList();
List<UndertaleSprite> allSprites = Data.Sprites.ToList();
List<UndertaleBackground> allBackgrounds = Data.Backgrounds.ToList();
List<UndertaleFont> allFonts = Data.Fonts.ToList();
List<UndertaleShader> allShaders = Data.Shaders.ToList();
List<UndertaleSound> allSounds = Data.Sounds.ToList();

int totalItems = allCode.Count + allSprites.Count + allBackgrounds.Count + allFonts.Count + allShaders.Count + allSounds.Count;

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
}

await StopProgressBarUpdater();
HideProgressBar();

async Task DumpCode()
{
    await Task.Run(() => Parallel.ForEach(allCode, DumpCodeItem));
}

void DumpCodeItem(UndertaleCode code)
{
    if (code is not null)
    {
        string path = Path.Combine(codeFolder, code.Name.Content + ".gml");
        try
        {
            File.WriteAllText(path, (code != null
                ? new Underanalyzer.Decompiler.DecompileContext(globalDecompileContext, code, decompilerSettings).DecompileToString()
                : ""));
        }
        catch (Exception e)
        {
            File.WriteAllText(path, "/*\nDECOMPILER FAILED!\n\n" + e.ToString() + "\n*/");
        }
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

PrintLine($"\n[ExportAllAssets] Summary for Mod {modNo}:");
PrintLine($"  Code - Exported: {allCode.Count}");
PrintLine($"  Sprites - Exported: {allSprites.Count}");
PrintLine($"  Backgrounds - Exported: {allBackgrounds.Count}");
PrintLine($"  Fonts - Exported: {allFonts.Count}");
PrintLine($"  Shaders - Exported: {allShaders.Count}");
PrintLine($"  Sounds - Exported: {allSounds.Count}");
PrintLine("[ExportAllAssets] Done.");

