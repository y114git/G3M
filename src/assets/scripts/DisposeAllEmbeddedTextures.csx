using System.Text;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using UndertaleModLib.Util;

EnsureDataLoaded();

int i = 0;
foreach (UndertaleEmbeddedTexture target in Data.EmbeddedTextures) 
{
    if (target is null)
    {
        i++;
        continue;
    }
    string filename = $"{i}.png";
    try
    {
        ScriptMessage($"Disposing {i}");
        target.Blank();
    }
    catch (Exception ex) 
    {
        ScriptMessage($"Failed to import {filename}: {ex.Message}");
    }
    i++;
}

ScriptMessage("Disposal complete.");
