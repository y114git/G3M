


using System;
using System.IO;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Reflection;
using UndertaleModLib.Util;

EnsureDataLoaded();

if (Data.IsVersionAtLeast(2024, 11))
{
    ScriptWarning("This script may act erroneously on GameMaker version 2024.11 and later.");
}


#load "SharedPaths.csx"

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
        var assemblyRoot = Directory.GetParent(Directory.GetParent(Assembly.GetEntryAssembly().Location));
        if (assemblyRoot != null && Directory.Exists(Path.Combine(assemblyRoot.FullName, "output")))
        {
            deltahubRoot = assemblyRoot.FullName;
        }
    }
}

if (deltahubRoot == null)
    throw new ScriptException("DELTAHUB root not found (no /output ancestor).");

string chapterNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "chapterNumber.txt"));
string modNo = File.ReadAllText(Path.Combine(deltahubRoot, "output", "Cache", "running", "modNumbersCache.txt"));
string assetNamePath = Path.Combine(deltahubRoot, "output", "xDeltaCombiner", chapterNo, modNo, "Objects", "AssetOrder.txt");
if (assetNamePath == null || !File.Exists(assetNamePath))
    throw new ScriptException("The asset name text file was not chosen or does not exist: " + assetNamePath);

string[] lines = File.ReadAllLines(@assetNamePath);

void Reorganize<T>(IList<T> list, List<string> order) where T : UndertaleNamedResource, new()
{
    Dictionary<string, T> temp = new Dictionary<string, T>();
    for (int i = 0; i < list.Count; i++)
    {
        T asset = list[i];
        string assetName = asset.Name?.Content;
        if (order.Contains(assetName))
            temp[assetName] = asset;
    }

    List<T> addOrder = new List<T>();
    for (int i = order.Count - 1; i >= 0; i--)
    {
        T asset;
        try
        {
            if (order[i] == "(null)")
                asset = default(T);
            else if (int.TryParse(order[i], out int index))
                asset = list[index];
            else
                asset = temp[order[i]];
        }
        catch (Exception e)
        {
            throw new ScriptException($"Missing asset with name \"{order[i]}\"");
        }
        addOrder.Add(asset);
    }

    foreach (T asset in addOrder)
        list.Remove(asset);
    foreach (T asset in addOrder)
        list.Insert(0, asset);
}

string currentType;
List<string> currentList = new List<string>();

void SubmitList()
{
    if (currentList.Count == 0)
        return;

    switch (currentType)
    {
        case "sounds":
            Reorganize<UndertaleSound>(Data.Sounds, currentList);
            break;
        case "sprites":
            Reorganize<UndertaleSprite>(Data.Sprites, currentList);
            break;
        case "backgrounds":
            Reorganize<UndertaleBackground>(Data.Backgrounds, currentList);
            break;
        case "paths":
            Reorganize<UndertalePath>(Data.Paths, currentList);
            break;
        case "scripts":
            Reorganize<UndertaleScript>(Data.Scripts, currentList);
            break;
        case "fonts":
            Reorganize<UndertaleFont>(Data.Fonts, currentList);
            break;
        case "objects":
            Reorganize<UndertaleGameObject>(Data.GameObjects, currentList);
            break;
        case "timelines":
            Reorganize<UndertaleTimeline>(Data.Timelines, currentList);
            break;
        case "rooms":
            Reorganize<UndertaleRoom>(Data.Rooms, currentList);
            break;
        case "shaders":
            Reorganize<UndertaleShader>(Data.Shaders, currentList);
            break;
        case "extensions":
            Reorganize<UndertaleExtension>(Data.Extensions, currentList);
            break;
    }
}

foreach (string line in lines)
{
    if (line.StartsWith("@@") && line.EndsWith("@@"))
    {
        SubmitList();
        currentType = line.Substring(2, line.Length - 4).ToLower();
        currentList.Clear();
    }
    else
        currentList.Add(line.Trim());
}
SubmitList();