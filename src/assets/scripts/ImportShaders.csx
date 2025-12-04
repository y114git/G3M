#load "SharedPaths.csx"

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

byte[] ReadAllBytesSafe(string path)
{
    try { return File.ReadAllBytes(path); } catch { return null; }
}

EnsureDataLoaded();

string deltahubRoot = FindDeltahubRoot();


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
        Console.WriteLine($"[ImportShaders] Using Objects directory next to data.win: {inputRoot}");
    }
}


if (inputRoot == null)
{
    if (string.IsNullOrWhiteSpace(chapterNo) || string.IsNullOrWhiteSpace(modNo))
        throw new ScriptException("chapterNumber/modNumbersCache missing in /output/Cache/running/.");

    string modRoot = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo);
    inputRoot = Path.Combine(modRoot, "Objects");
    Console.WriteLine($"[ImportShaders] Using Objects directory from modNumbersCache: {inputRoot}");
}

string shadersIn = Path.Combine(inputRoot, "Shaders");

if (!Directory.Exists(shadersIn))
{
    PrintLine("[ImportShaders] No Shaders directory found, skipping.");
    return;
}


void ImportShader(string shaderDir)
{
    string shaderName = Path.GetFileName(shaderDir);
    if (string.IsNullOrEmpty(shaderName))
        return;
    
    
    UndertaleShader shader = Data.Shaders.ByName(shaderName);
    if (shader == null)
    {
        shader = new UndertaleShader();
        shader.Name = new UndertaleString(shaderName);
        Data.Strings.Add(shader.Name);
        Data.Shaders.Add(shader);
        PrintLine($"[ImportShaders] Created new shader: {shaderName}");
    }
    else
    {
        PrintLine($"[ImportShaders] Updating existing shader: {shaderName}");
    }
    
    
    string typeFile = Path.Combine(shaderDir, "Type.txt");
    if (File.Exists(typeFile))
    {
        string shaderTypeStr = ReadAllTextSafe(typeFile);
        if (!string.IsNullOrEmpty(shaderTypeStr))
        {
            if (Enum.TryParse<UndertaleShader.ShaderType>(shaderTypeStr, out var shaderType))
            {
                shader.Type = shaderType;
            }
        }
    }
    
    
    string glslEsFrag = Path.Combine(shaderDir, "GLSL_ES_Fragment.txt");
    if (File.Exists(glslEsFrag))
    {
        string code = ReadAllTextSafe(glslEsFrag);
        if (shader.GLSL_ES_Fragment == null)
            shader.GLSL_ES_Fragment = new UndertaleString(code ?? "");
        else
            shader.GLSL_ES_Fragment.Content = code ?? "";
        if (!Data.Strings.Any(s => s == shader.GLSL_ES_Fragment))
            Data.Strings.Add(shader.GLSL_ES_Fragment);
    }
    
    string glslEsVert = Path.Combine(shaderDir, "GLSL_ES_Vertex.txt");
    if (File.Exists(glslEsVert))
    {
        string code = ReadAllTextSafe(glslEsVert);
        if (shader.GLSL_ES_Vertex == null)
            shader.GLSL_ES_Vertex = new UndertaleString(code ?? "");
        else
            shader.GLSL_ES_Vertex.Content = code ?? "";
        if (!Data.Strings.Any(s => s == shader.GLSL_ES_Vertex))
            Data.Strings.Add(shader.GLSL_ES_Vertex);
    }
    
    
    string glslFrag = Path.Combine(shaderDir, "GLSL_Fragment.txt");
    if (File.Exists(glslFrag))
    {
        string code = ReadAllTextSafe(glslFrag);
        if (shader.GLSL_Fragment == null)
            shader.GLSL_Fragment = new UndertaleString(code ?? "");
        else
            shader.GLSL_Fragment.Content = code ?? "";
        if (!Data.Strings.Any(s => s == shader.GLSL_Fragment))
            Data.Strings.Add(shader.GLSL_Fragment);
    }
    
    string glslVert = Path.Combine(shaderDir, "GLSL_Vertex.txt");
    if (File.Exists(glslVert))
    {
        string code = ReadAllTextSafe(glslVert);
        if (shader.GLSL_Vertex == null)
            shader.GLSL_Vertex = new UndertaleString(code ?? "");
        else
            shader.GLSL_Vertex.Content = code ?? "";
        if (!Data.Strings.Any(s => s == shader.GLSL_Vertex))
            Data.Strings.Add(shader.GLSL_Vertex);
    }
    
    
    string hlsl9Frag = Path.Combine(shaderDir, "HLSL9_Fragment.txt");
    if (File.Exists(hlsl9Frag))
    {
        string code = ReadAllTextSafe(hlsl9Frag);
        if (shader.HLSL9_Fragment == null)
            shader.HLSL9_Fragment = new UndertaleString(code ?? "");
        else
            shader.HLSL9_Fragment.Content = code ?? "";
        if (!Data.Strings.Any(s => s == shader.HLSL9_Fragment))
            Data.Strings.Add(shader.HLSL9_Fragment);
    }
    
    string hlsl9Vert = Path.Combine(shaderDir, "HLSL9_Vertex.txt");
    if (File.Exists(hlsl9Vert))
    {
        string code = ReadAllTextSafe(hlsl9Vert);
        if (shader.HLSL9_Vertex == null)
            shader.HLSL9_Vertex = new UndertaleString(code ?? "");
        else
            shader.HLSL9_Vertex.Content = code ?? "";
        if (!Data.Strings.Any(s => s == shader.HLSL9_Vertex))
            Data.Strings.Add(shader.HLSL9_Vertex);
    }
    
    
    string hlsl11Vert = Path.Combine(shaderDir, "HLSL11_VertexData.bin");
    if (File.Exists(hlsl11Vert))
    {
        byte[] data = ReadAllBytesSafe(hlsl11Vert);
        if (data != null && data.Length > 0)
        {
            if (shader.HLSL11_VertexData == null)
                shader.HLSL11_VertexData = new UndertaleShader.UndertaleRawShaderData();
            shader.HLSL11_VertexData.Data = data;
            shader.HLSL11_VertexData.IsNull = false;
        }
    }
    
    string hlsl11Pix = Path.Combine(shaderDir, "HLSL11_PixelData.bin");
    if (File.Exists(hlsl11Pix))
    {
        byte[] data = ReadAllBytesSafe(hlsl11Pix);
        if (data != null && data.Length > 0)
        {
            if (shader.HLSL11_PixelData == null)
                shader.HLSL11_PixelData = new UndertaleShader.UndertaleRawShaderData();
            shader.HLSL11_PixelData.Data = data;
            shader.HLSL11_PixelData.IsNull = false;
        }
    }
    
    string psslVert = Path.Combine(shaderDir, "PSSL_VertexData.bin");
    if (File.Exists(psslVert))
    {
        byte[] data = ReadAllBytesSafe(psslVert);
        if (data != null && data.Length > 0)
        {
            if (shader.PSSL_VertexData == null)
                shader.PSSL_VertexData = new UndertaleShader.UndertaleRawShaderData();
            shader.PSSL_VertexData.Data = data;
            shader.PSSL_VertexData.IsNull = false;
        }
    }
    
    string psslPix = Path.Combine(shaderDir, "PSSL_PixelData.bin");
    if (File.Exists(psslPix))
    {
        byte[] data = ReadAllBytesSafe(psslPix);
        if (data != null && data.Length > 0)
        {
            if (shader.PSSL_PixelData == null)
                shader.PSSL_PixelData = new UndertaleShader.UndertaleRawShaderData();
            shader.PSSL_PixelData.Data = data;
            shader.PSSL_PixelData.IsNull = false;
        }
    }
    
    string cgVitaVert = Path.Combine(shaderDir, "Cg_PSVita_VertexData.bin");
    if (File.Exists(cgVitaVert))
    {
        byte[] data = ReadAllBytesSafe(cgVitaVert);
        if (data != null && data.Length > 0)
        {
            if (shader.Cg_PSVita_VertexData == null)
                shader.Cg_PSVita_VertexData = new UndertaleShader.UndertaleRawShaderData();
            shader.Cg_PSVita_VertexData.Data = data;
            shader.Cg_PSVita_VertexData.IsNull = false;
        }
    }
    
    string cgVitaPix = Path.Combine(shaderDir, "Cg_PSVita_PixelData.bin");
    if (File.Exists(cgVitaPix))
    {
        byte[] data = ReadAllBytesSafe(cgVitaPix);
        if (data != null && data.Length > 0)
        {
            if (shader.Cg_PSVita_PixelData == null)
                shader.Cg_PSVita_PixelData = new UndertaleShader.UndertaleRawShaderData();
            shader.Cg_PSVita_PixelData.Data = data;
            shader.Cg_PSVita_PixelData.IsNull = false;
        }
    }
    
    string cgPs3Vert = Path.Combine(shaderDir, "Cg_PS3_VertexData.bin");
    if (File.Exists(cgPs3Vert))
    {
        byte[] data = ReadAllBytesSafe(cgPs3Vert);
        if (data != null && data.Length > 0)
        {
            if (shader.Cg_PS3_VertexData == null)
                shader.Cg_PS3_VertexData = new UndertaleShader.UndertaleRawShaderData();
            shader.Cg_PS3_VertexData.Data = data;
            shader.Cg_PS3_VertexData.IsNull = false;
        }
    }
    
    string cgPs3Pix = Path.Combine(shaderDir, "Cg_PS3_PixelData.bin");
    if (File.Exists(cgPs3Pix))
    {
        byte[] data = ReadAllBytesSafe(cgPs3Pix);
        if (data != null && data.Length > 0)
        {
            if (shader.Cg_PS3_PixelData == null)
                shader.Cg_PS3_PixelData = new UndertaleShader.UndertaleRawShaderData();
            shader.Cg_PS3_PixelData.Data = data;
            shader.Cg_PS3_PixelData.IsNull = false;
        }
    }
    
    
    string attrsFile = Path.Combine(shaderDir, "VertexShaderAttributes.txt");
    if (File.Exists(attrsFile))
    {
        string attrsText = ReadAllTextSafe(attrsFile);
        if (!string.IsNullOrEmpty(attrsText))
        {
            if (shader.VertexShaderAttributes == null)
                shader.VertexShaderAttributes = new UndertalePointerList<UndertaleString>();
            shader.VertexShaderAttributes.Clear();
            foreach (var line in attrsText.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
            {
                if (!string.IsNullOrWhiteSpace(line))
                {
                    var attr = new UndertaleString(line.Trim());
                    Data.Strings.Add(attr);
                    shader.VertexShaderAttributes.Add(attr);
                }
            }
        }
    }
}


int shadersImported = 0;
int shadersUpdated = 0;

if (Directory.Exists(shadersIn))
{
    var shaderDirs = Directory.GetDirectories(shadersIn);
    foreach (var shaderDir in shaderDirs)
    {
        try
        {
            bool shaderExisted = Data.Shaders.ByName(Path.GetFileName(shaderDir)) != null;
            ImportShader(shaderDir);
            if (shaderExisted) shadersUpdated++; else shadersImported++;
        }
        catch (Exception e)
        {
            PrintLine($"[ImportShaders] ERROR: Failed to import {shaderDir}: {e.Message}");
            PrintLine($"[ImportShaders] Stack trace: {e.StackTrace}");
        }
    }
}


Data.SaveFile(Data.FilePath);

PrintLine($"\n[ImportShaders] Summary for Mod {modNo}:");
PrintLine($"  Shaders - Imported: {shadersImported}, Updated: {shadersUpdated}");
PrintLine("[ImportShaders] Done.");

