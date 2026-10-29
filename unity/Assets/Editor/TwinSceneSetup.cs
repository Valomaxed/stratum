using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class TwinSceneSetup
{
    [InitializeOnLoadMethod]
    private static void ResumeRuntimeVerification()
    {
        if(SessionState.GetBool("TwinVerifyRuntime",false)) EditorApplication.update+=CheckRuntime;
    }

    public static void VerifyRuntime()
    {
        CreateScene();
        SessionState.SetBool("TwinVerifyRuntime",true);
        SessionState.SetBool("TwinVerifyLateral",false);
        SessionState.SetBool("TwinVerifySpace",false);
        SessionState.SetBool("TwinVerifyBridge",false);
        SessionState.SetBool("TwinVerifySpaceWind",false);
        SessionState.SetBool("TwinVerifySparse",false);
        SessionState.SetFloat("TwinVerifyDeadline",(float)EditorApplication.timeSinceStartup+120);
        EditorApplication.update-=CheckRuntime;
        EditorApplication.update+=CheckRuntime;
        EditorApplication.EnterPlaymode();
    }

    private static void CheckRuntime()
    {
        if(EditorApplication.timeSinceStartup>SessionState.GetFloat("TwinVerifyDeadline",0))
        {
            SessionState.SetBool("TwinVerifyRuntime",false);EditorApplication.update-=CheckRuntime;
            Debug.LogError("Unity runtime verification timed out waiting for Python API.");EditorApplication.Exit(1);return;
        }
        var twin=Object.FindFirstObjectByType<StructuralTwin>();
        if(EditorApplication.isPlaying && twin!=null && twin.IsReady)
        {
            if(!SessionState.GetBool("TwinVerifySpace",false))
            {
                if(!twin.IsSpace3D || twin.MemberCount!=78){Debug.LogError("Expected 78-member 3D truss");EditorApplication.Exit(1);return;}
                if(!SessionState.GetBool("TwinVerifySpaceWind",false)){SessionState.SetBool("TwinVerifySpaceWind",true);twin.VerifyLateralCase();return;}
                if(twin.DisplayCase!="LC3")return;
                if(!twin.HasTransverseResponse || !twin.HasTransverseLoads){Debug.LogError("Missing 3D transverse response/load");EditorApplication.Exit(1);return;}
                SessionState.SetBool("TwinVerifySpace",true);twin.VerifyBridgeCase();return;
            }
            if(!SessionState.GetBool("TwinVerifyBridge",false))
            {
                if(!twin.IsBridge)return;
                if(!twin.BridgeVerified){Debug.LogError("Bridge bearing/envelope verification failed");EditorApplication.Exit(1);return;}
                SessionState.SetBool("TwinVerifyBridge",true);twin.VerifyPlanarCase();return;
            }
            if(twin.IsSpace3D)return;
            if(twin.LoadCaseCount!=3 || twin.SensitivityRank!=21) { Debug.LogError("Expected three load cases and rank 21");EditorApplication.Exit(1);return; }
            if(!SessionState.GetBool("TwinVerifyLateral",false)) { SessionState.SetBool("TwinVerifyLateral",true);twin.VerifyLateralCase();return; }
            if(twin.DisplayCase!="LC3")return;
            if(!SessionState.GetBool("TwinVerifySparse",false)){SessionState.SetBool("TwinVerifySparse",true);twin.VerifySparseHealthy();return;}
            if(!twin.IsSparseHealthy)return;
            System.IO.File.WriteAllText("../data/unity-runtime-validation.json", "{\"api_connected\": true, \"space_3d_validated\": true, \"bridge_validated\": true, \"space_members\": 78, \"members\": "+twin.MemberCount+", \"load_cases\": 3, \"sensitivity_rank\": 21, \"display_case\": \"LC3\", \"noise_aware_sparse\": true, \"healthy_zero_alarms\": true, \"scene_objects\": "+twin.RenderedObjectCount+"}");
            SessionState.SetBool("TwinVerifyRuntime",false); EditorApplication.update-=CheckRuntime;
            Debug.Log("Unity runtime verification: API connected and scene populated.");
            EditorApplication.Exit(0);
        }
    }

    [MenuItem("Twin/Create Demo Scene")]
    public static void CreateScene()
    {
        var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
        var root=new GameObject("Structural Twin"); root.AddComponent<StructuralTwin>();
        System.IO.Directory.CreateDirectory("Assets/Scenes");
        EditorSceneManager.SaveScene(scene,"Assets/Scenes/StructuralTwin.unity");
        EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene("Assets/Scenes/StructuralTwin.unity",true)};
        Debug.Log("Structural Twin demo scene created.");
    }

    // Batch verification entry point: creates the scene and checks the C# assembly loaded.
    public static void Verify()
    {
        CreateScene();
        System.IO.File.WriteAllText("../data/unity-validation.json", "{\"compiled\": true, \"scene_created\": true}");
    }
}
