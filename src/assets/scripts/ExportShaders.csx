

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

object GetProp(object obj, string name)
    => obj?.GetType().GetProperty(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.IgnoreCase)?.GetValue(obj);

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
string shadersOut      = Path.Combine(outputRoot, "Shaders");

Directory.CreateDirectory(outputRoot);
Directory.CreateDirectory(shadersOut);


UndertaleData comparison = null;
Dictionary<string, UndertaleShader> comparisonShaders = new Dictionary<string, UndertaleShader>();
if (File.Exists(comparisonPath))
{
    PrintLine($"[ExportShaders] Loading comparison file from: {comparisonPath}");
    using (var fs = new FileStream(comparisonPath, FileMode.Open, FileAccess.Read, FileShare.Read))
        comparison = UndertaleIO.Read(fs);
    if (comparison != null)
    {
        foreach (var shader in comparison.Shaders)
        {
            if (shader?.Name?.Content != null)
                comparisonShaders[shader.Name.Content] = shader;
        }
    }
}


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
    
    
    if (shader.HLSL11_VertexData != null && shader.HLSL11_VertexData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "HLSL11_VertexData.bin"), shader.HLSL11_VertexData);
    if (shader.HLSL11_PixelData != null && shader.HLSL11_PixelData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "HLSL11_PixelData.bin"), shader.HLSL11_PixelData);
    if (shader.PSSL_VertexData != null && shader.PSSL_VertexData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "PSSL_VertexData.bin"), shader.PSSL_VertexData);
    if (shader.PSSL_PixelData != null && shader.PSSL_PixelData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "PSSL_PixelData.bin"), shader.PSSL_PixelData);
    if (shader.Cg_PSVita_VertexData != null && shader.Cg_PSVita_VertexData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PSVita_VertexData.bin"), shader.Cg_PSVita_VertexData);
    if (shader.Cg_PSVita_PixelData != null && shader.Cg_PSVita_PixelData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PSVita_PixelData.bin"), shader.Cg_PSVita_PixelData);
    if (shader.Cg_PS3_VertexData != null && shader.Cg_PS3_VertexData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PS3_VertexData.bin"), shader.Cg_PS3_VertexData);
    if (shader.Cg_PS3_PixelData != null && shader.Cg_PS3_PixelData.Length > 0)
        File.WriteAllBytes(Path.Combine(outputDir, "Cg_PS3_PixelData.bin"), shader.Cg_PS3_PixelData);
    
    
    if (shader.VertexShaderAttributes != null && shader.VertexShaderAttributes.Count > 0)
    {
        var attrs = new StringBuilder();
        foreach (var attr in shader.VertexShaderAttributes)
        {
            attrs.AppendLine(attr?.Content ?? "");
        }
        File.WriteAllText(Path.Combine(outputDir, "VertexShaderAttributes.txt"), attrs.ToString(), Encoding.UTF8);
    }
}


int shadersNew = 0, shadersChanged = 0;

foreach (var shader in Data.Shaders)
{
    if (shader?.Name?.Content == null) continue;
    
    string shaderName = shader.Name.Content;
    bool isNew = !comparisonShaders.ContainsKey(shaderName);
    bool isChanged = false;
    
    if (!isNew)
    {
        var compShader = comparisonShaders[shaderName];
        
        if (shader.Type != compShader.Type ||
            (shader.GLSL_ES_Fragment?.Content ?? "") != (compShader.GLSL_ES_Fragment?.Content ?? "") ||
            (shader.GLSL_ES_Vertex?.Content ?? "") != (compShader.GLSL_ES_Vertex?.Content ?? "") ||
            (shader.GLSL_Fragment?.Content ?? "") != (compShader.GLSL_Fragment?.Content ?? "") ||
            (shader.GLSL_Vertex?.Content ?? "") != (compShader.GLSL_Vertex?.Content ?? ""))
        {
            isChanged = true;
        }
    }
    
    if (isNew || isChanged)
    {
        string shaderDir = Path.Combine(shadersOut, SafeName(shaderName));
        ExportShader(shader, shaderDir);
        PrintLine($"[Shader] {shaderName}: {(isNew ? "NEW" : "CHANGED")}");
        if (isNew) shadersNew++; else shadersChanged++;
    }
}

PrintLine($"\n[ExportShaders] Summary for Mod {modNo}:");
PrintLine($"  Shaders - New: {shadersNew}, Changed: {shadersChanged}");
PrintLine("[ExportShaders] Done.");

