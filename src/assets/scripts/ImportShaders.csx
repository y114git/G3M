


using System;
using System.IO;
using System.Linq;
using UndertaleModLib;
using UndertaleModLib.Models;




string InputDirectory = "";




void PrintLine(string s) => Console.WriteLine(s);

string ResolveInputDirectory()
{
    if (!string.IsNullOrEmpty(InputDirectory) && Directory.Exists(InputDirectory))
        return InputDirectory;

    if (string.IsNullOrEmpty(FilePath))
        throw new ScriptException("No data.win file loaded. Please load a game data file first.");

    string dataWinDir = Path.GetDirectoryName(FilePath);
    string shadersDir = Path.Combine(dataWinDir, "Objects", "Shaders");
    
    if (Directory.Exists(shadersDir))
        return shadersDir;

    throw new ScriptException($"Shaders directory not found at: {shadersDir}\nPlease specify InputDirectory or place shaders in an 'Objects/Shaders' folder next to data.win.");
}




EnsureDataLoaded();

string shadersIn = ResolveInputDirectory();
PrintLine($"[ImportShaders] Importing from: {shadersIn}");

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
    }

    string typeFile = Path.Combine(shaderDir, "Type.txt");
    if (File.Exists(typeFile))
    {
        try
        {
            string shaderTypeStr = File.ReadAllText(typeFile);
            if (!string.IsNullOrEmpty(shaderTypeStr) && Enum.TryParse<UndertaleShader.ShaderType>(shaderTypeStr, out var shaderType))
            {
                shader.Type = shaderType;
            }
        }
        catch { }
    }

    string[] shaderFiles = {
        "GLSL_ES_Fragment.txt", "GLSL_ES_Vertex.txt",
        "GLSL_Fragment.txt", "GLSL_Vertex.txt",
        "HLSL9_Fragment.txt", "HLSL9_Vertex.txt"
    };

    foreach (string fileName in shaderFiles)
    {
        string filePath = Path.Combine(shaderDir, fileName);
        if (File.Exists(filePath))
        {
            try
            {
                string code = File.ReadAllText(filePath);
                UndertaleString shaderString = null;
                switch (fileName)
                {
                    case "GLSL_ES_Fragment.txt":
                        if (shader.GLSL_ES_Fragment == null)
                            shader.GLSL_ES_Fragment = new UndertaleString(code);
                        else
                            shader.GLSL_ES_Fragment.Content = code;
                        shaderString = shader.GLSL_ES_Fragment;
                        break;
                    case "GLSL_ES_Vertex.txt":
                        if (shader.GLSL_ES_Vertex == null)
                            shader.GLSL_ES_Vertex = new UndertaleString(code);
                        else
                            shader.GLSL_ES_Vertex.Content = code;
                        shaderString = shader.GLSL_ES_Vertex;
                        break;
                    case "GLSL_Fragment.txt":
                        if (shader.GLSL_Fragment == null)
                            shader.GLSL_Fragment = new UndertaleString(code);
                        else
                            shader.GLSL_Fragment.Content = code;
                        shaderString = shader.GLSL_Fragment;
                        break;
                    case "GLSL_Vertex.txt":
                        if (shader.GLSL_Vertex == null)
                            shader.GLSL_Vertex = new UndertaleString(code);
                        else
                            shader.GLSL_Vertex.Content = code;
                        shaderString = shader.GLSL_Vertex;
                        break;
                    case "HLSL9_Fragment.txt":
                        if (shader.HLSL9_Fragment == null)
                            shader.HLSL9_Fragment = new UndertaleString(code);
                        else
                            shader.HLSL9_Fragment.Content = code;
                        shaderString = shader.HLSL9_Fragment;
                        break;
                    case "HLSL9_Vertex.txt":
                        if (shader.HLSL9_Vertex == null)
                            shader.HLSL9_Vertex = new UndertaleString(code);
                        else
                            shader.HLSL9_Vertex.Content = code;
                        shaderString = shader.HLSL9_Vertex;
                        break;
                }
                if (shaderString != null && !Data.Strings.Any(s => s == shaderString))
                    Data.Strings.Add(shaderString);
            }
            catch { }
        }
    }

    string[] binaryFiles = {
        "HLSL11_VertexData.bin", "HLSL11_PixelData.bin",
        "PSSL_VertexData.bin", "PSSL_PixelData.bin",
        "Cg_PSVita_VertexData.bin", "Cg_PSVita_PixelData.bin",
        "Cg_PS3_VertexData.bin", "Cg_PS3_PixelData.bin"
    };

    foreach (string fileName in binaryFiles)
    {
        string filePath = Path.Combine(shaderDir, fileName);
        if (File.Exists(filePath))
        {
            try
            {
                byte[] data = File.ReadAllBytes(filePath);
                if (data != null && data.Length > 0)
                {
                    switch (fileName)
                    {
                        case "HLSL11_VertexData.bin":
                            if (shader.HLSL11_VertexData == null)
                                shader.HLSL11_VertexData = new UndertaleShader.UndertaleRawShaderData();
                            shader.HLSL11_VertexData.Data = data;
                            shader.HLSL11_VertexData.IsNull = false;
                            break;
                        case "HLSL11_PixelData.bin":
                            if (shader.HLSL11_PixelData == null)
                                shader.HLSL11_PixelData = new UndertaleShader.UndertaleRawShaderData();
                            shader.HLSL11_PixelData.Data = data;
                            shader.HLSL11_PixelData.IsNull = false;
                            break;
                        case "PSSL_VertexData.bin":
                            if (shader.PSSL_VertexData == null)
                                shader.PSSL_VertexData = new UndertaleShader.UndertaleRawShaderData();
                            shader.PSSL_VertexData.Data = data;
                            shader.PSSL_VertexData.IsNull = false;
                            break;
                        case "PSSL_PixelData.bin":
                            if (shader.PSSL_PixelData == null)
                                shader.PSSL_PixelData = new UndertaleShader.UndertaleRawShaderData();
                            shader.PSSL_PixelData.Data = data;
                            shader.PSSL_PixelData.IsNull = false;
                            break;
                        case "Cg_PSVita_VertexData.bin":
                            if (shader.Cg_PSVita_VertexData == null)
                                shader.Cg_PSVita_VertexData = new UndertaleShader.UndertaleRawShaderData();
                            shader.Cg_PSVita_VertexData.Data = data;
                            shader.Cg_PSVita_VertexData.IsNull = false;
                            break;
                        case "Cg_PSVita_PixelData.bin":
                            if (shader.Cg_PSVita_PixelData == null)
                                shader.Cg_PSVita_PixelData = new UndertaleShader.UndertaleRawShaderData();
                            shader.Cg_PSVita_PixelData.Data = data;
                            shader.Cg_PSVita_PixelData.IsNull = false;
                            break;
                        case "Cg_PS3_VertexData.bin":
                            if (shader.Cg_PS3_VertexData == null)
                                shader.Cg_PS3_VertexData = new UndertaleShader.UndertaleRawShaderData();
                            shader.Cg_PS3_VertexData.Data = data;
                            shader.Cg_PS3_VertexData.IsNull = false;
                            break;
                        case "Cg_PS3_PixelData.bin":
                            if (shader.Cg_PS3_PixelData == null)
                                shader.Cg_PS3_PixelData = new UndertaleShader.UndertaleRawShaderData();
                            shader.Cg_PS3_PixelData.Data = data;
                            shader.Cg_PS3_PixelData.IsNull = false;
                            break;
                    }
                }
            }
            catch { }
        }
    }

    
    string attrsFile = Path.Combine(shaderDir, "VertexShaderAttributes.txt");
    if (File.Exists(attrsFile))
    {
        try
        {
            string attrsText = File.ReadAllText(attrsFile);
            if (!string.IsNullOrEmpty(attrsText))
            {
                if (shader.VertexShaderAttributes == null)
                    shader.VertexShaderAttributes = new UndertaleSimpleList<UndertaleShader.VertexShaderAttribute>();
                shader.VertexShaderAttributes.Clear();
                foreach (var line in attrsText.Split(new[] { '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries))
                {
                    if (!string.IsNullOrWhiteSpace(line))
                    {
                        var attrName = new UndertaleString(line.Trim());
                        Data.Strings.Add(attrName);
                        var attr = new UndertaleShader.VertexShaderAttribute();
                        attr.Name = attrName;
                        shader.VertexShaderAttributes.Add(attr);
                    }
                }
            }
        }
        catch { }
    }
}

int shadersImported = 0;
int shadersUpdated = 0;

var shaderDirs = Directory.GetDirectories(shadersIn);
foreach (var shaderDir in shaderDirs)
{
    try
    {
        string shaderName = Path.GetFileName(shaderDir);
        bool shaderExisted = Data.Shaders.ByName(shaderName) != null;
        ImportShader(shaderDir);
        if (shaderExisted) shadersUpdated++; else shadersImported++;
    }
    catch (Exception e)
    {
        PrintLine($"[ImportShaders] ERROR: Failed to import {shaderDir}: {e.Message}");
    }
}

PrintLine($"[ImportShaders] Import complete. {shadersImported} new, {shadersUpdated} updated.");
