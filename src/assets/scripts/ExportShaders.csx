


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




EnsureDataLoaded();

string shadersOut = GetOutputDirectory();
PrintLine($"[ExportShaders] Exporting to: {shadersOut}");

List<UndertaleShader> allShaders = Data.Shaders.ToList();
PrintLine($"[ExportShaders] Found {allShaders.Count} shaders to export.");

SetProgressBar(null, "Exporting Shaders", 0, allShaders.Count);
StartProgressBarUpdater();

await Task.Run(() => Parallel.ForEach(allShaders, shader => ExportShader(shader, shadersOut)));

void ExportShader(UndertaleShader shader, string outputDir)
{
    if (shader?.Name?.Content == null)
    {
        IncrementProgressParallel();
        return;
    }

    try
    {
        string name = SafeName(shader.Name.Content);
        string shaderDir = Path.Combine(outputDir, name);
        Directory.CreateDirectory(shaderDir);

        
        File.WriteAllText(Path.Combine(shaderDir, "Type.txt"), shader.Type.ToString(), Encoding.UTF8);

        
        if (shader.GLSL_ES_Fragment != null)
            File.WriteAllText(Path.Combine(shaderDir, "GLSL_ES_Fragment.txt"), shader.GLSL_ES_Fragment.Content ?? "", Encoding.UTF8);
        if (shader.GLSL_ES_Vertex != null)
            File.WriteAllText(Path.Combine(shaderDir, "GLSL_ES_Vertex.txt"), shader.GLSL_ES_Vertex.Content ?? "", Encoding.UTF8);
        if (shader.GLSL_Fragment != null)
            File.WriteAllText(Path.Combine(shaderDir, "GLSL_Fragment.txt"), shader.GLSL_Fragment.Content ?? "", Encoding.UTF8);
        if (shader.GLSL_Vertex != null)
            File.WriteAllText(Path.Combine(shaderDir, "GLSL_Vertex.txt"), shader.GLSL_Vertex.Content ?? "", Encoding.UTF8);

        
        if (shader.HLSL9_Fragment != null)
            File.WriteAllText(Path.Combine(shaderDir, "HLSL9_Fragment.txt"), shader.HLSL9_Fragment.Content ?? "", Encoding.UTF8);
        if (shader.HLSL9_Vertex != null)
            File.WriteAllText(Path.Combine(shaderDir, "HLSL9_Vertex.txt"), shader.HLSL9_Vertex.Content ?? "", Encoding.UTF8);

        
        if (shader.HLSL11_VertexData?.Data != null && shader.HLSL11_VertexData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "HLSL11_VertexData.bin"), shader.HLSL11_VertexData.Data);
        if (shader.HLSL11_PixelData?.Data != null && shader.HLSL11_PixelData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "HLSL11_PixelData.bin"), shader.HLSL11_PixelData.Data);
        if (shader.PSSL_VertexData?.Data != null && shader.PSSL_VertexData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "PSSL_VertexData.bin"), shader.PSSL_VertexData.Data);
        if (shader.PSSL_PixelData?.Data != null && shader.PSSL_PixelData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "PSSL_PixelData.bin"), shader.PSSL_PixelData.Data);
        if (shader.Cg_PSVita_VertexData?.Data != null && shader.Cg_PSVita_VertexData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "Cg_PSVita_VertexData.bin"), shader.Cg_PSVita_VertexData.Data);
        if (shader.Cg_PSVita_PixelData?.Data != null && shader.Cg_PSVita_PixelData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "Cg_PSVita_PixelData.bin"), shader.Cg_PSVita_PixelData.Data);
        if (shader.Cg_PS3_VertexData?.Data != null && shader.Cg_PS3_VertexData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "Cg_PS3_VertexData.bin"), shader.Cg_PS3_VertexData.Data);
        if (shader.Cg_PS3_PixelData?.Data != null && shader.Cg_PS3_PixelData.Data.Length > 0)
            File.WriteAllBytes(Path.Combine(shaderDir, "Cg_PS3_PixelData.bin"), shader.Cg_PS3_PixelData.Data);

        
        if (shader.VertexShaderAttributes != null && shader.VertexShaderAttributes.Count > 0)
        {
            var attrs = new StringBuilder();
            foreach (var attr in shader.VertexShaderAttributes)
            {
                if (attr?.Name?.Content != null)
                    attrs.AppendLine(attr.Name.Content);
            }
            File.WriteAllText(Path.Combine(shaderDir, "VertexShaderAttributes.txt"), attrs.ToString(), Encoding.UTF8);
        }

        
        var meta = new Dictionary<string, object>
        {
            ["name"] = shader.Name.Content,
            ["type"] = shader.Type.ToString()
        };
        string metaJson = JsonSerializer.Serialize(meta, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(Path.Combine(shaderDir, $"{name}.json"), metaJson, Encoding.UTF8);
    }
    catch (Exception ex)
    {
        PrintLine($"[ExportShaders] Failed to export shader {shader.Name?.Content}: {ex.Message}");
    }

    IncrementProgressParallel();
}

await StopProgressBarUpdater();
HideProgressBar();

PrintLine($"[ExportShaders] Export complete. {allShaders.Count} shaders exported to {shadersOut}");
