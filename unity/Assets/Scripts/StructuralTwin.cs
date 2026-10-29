using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

// Scene and controls are generated at runtime. No third-party Unity packages.
public class StructuralTwin : MonoBehaviour
{
    public string apiUrl = "http://127.0.0.1:8766";
    public float deformationScale = 150f;
    public bool startIn3D = true;
    private string modelId="space";
    private int sensorCapacity=132;
    private BridgeSettings bridgeSettings=new BridgeSettings();
    private readonly List<Mesh> ownedMeshes=new List<Mesh>();
    private TwinResponse data;
    private bool sceneBuilt;
    private float[] loss = new float[78];
    private readonly List<GameObject> rods = new List<GameObject>();
    private readonly List<GameObject> joints = new List<GameObject>();
    private readonly List<Material> ownedMaterials = new List<Material>();
    private GameObject geometry;
    private Camera viewCamera;
    private int selected = 4;
    private float yaw = -32f, pitch = 18f, distance = 32f;
    private bool busy, stressView, deformed, physics, estimatedDamage, showLoads = true, showSensors = true;
    private string message = "Connecting to Python FEM…";
    private Vector2 down;
    private Vector2 controlsScroll;
    private bool multipleLoads=true;
    private bool noiseAware=true;
    private float sensorNoise=.005f;
    private int displayCase=0, sensorBudget=132;
    private float maxDrag;
    public bool IsReady { get { return data!=null && !busy && sceneBuilt; } }
    public int MemberCount { get { return data==null?0:data.members.Length; } }
    public int RenderedObjectCount { get { return geometry==null?0:geometry.GetComponentsInChildren<Renderer>().Length; } }
    public int LoadCaseCount { get { return data==null||data.excitation==null?0:data.excitation.case_count; } }
    public string DisplayCase { get { return data==null||data.excitation==null?"":data.excitation.display_case; } }
    public int SensitivityRank { get { return data==null||data.excitation==null?0:data.excitation.observability.rank; } }
    public bool IsSpace3D { get { return data!=null && data.dimension==3; } }
    public bool HasTransverseResponse
    {
        get { if(data==null)return false;foreach(var n in data.nodes)if(Mathf.Abs(n.uz)>1e-6f)return true;return false; }
    }
    public bool HasTransverseLoads
    {
        get { if(data==null)return false;foreach(var f in data.loads)if(Mathf.Abs(f.fz)>0)return true;return false; }
    }
    public bool IsBridge { get { return data!=null && data.model_id=="bridge"; } }
    private int BridgePanelCount { get { int count=0;if(geometry!=null)foreach(var item in geometry.GetComponentsInChildren<Transform>())if(item.name=="Idealized deck panel")count++;return count; } }
    public bool BridgeVerified { get { return IsBridge && rods.Count==78 && BridgePanelCount==4 && data.bridge!=null && data.supports.Length==4 && data.summary.sensor_capacity==131 && Mathf.Abs(data.bridge.current.vertical_balance_error_kn)<1e-5f && data.bridge.sweep.peak_down_mm>=data.bridge.current.deck_down_mm-.0001f; } }
    public void VerifyBridgeCase() { SwitchModelId("bridge"); }
    public void VerifyPlanarCase() { SwitchModel(false); }
    public void VerifyLateralCase() { displayCase=2; StartCoroutine(Analyze()); }
    public void VerifySparseHealthy() { Array.Clear(loss,0,loss.Length);physics=true;noiseAware=true;sensorNoise=0;StartCoroutine(Analyze()); }
    public bool IsSparseHealthy
    {
        get
        {
            if(data==null||data.prediction==null||data.prediction.physics==null||data.prediction.physics.method!="Noise-aware sparse physics")return false;
            foreach(float severity in data.prediction.severity)if(severity>=.05f)return false;
            return true;
        }
    }

    [Serializable] public class Node { public int id; public float x,y,z,ux,uy,uz; }
    [Serializable] public class Member { public int id,a,b; public string name; public float length,area,elastic_modulus,effective_modulus,damage,stress,strain,axial_force; }
    [Serializable] public class Support { public int node; public string type; }
    [Serializable] public class Load { public int node; public float fx,fy,fz; }
    [Serializable] public class Sensor { public string id,kind; public int member,node,axis; public bool active; }
    [Serializable] public class PhysicsInfo { public bool converged;public string method,noise_source,reason;public float noise_std,estimated_common_bias; }
    [Serializable] public class Prediction { public bool available; public string reason,method; public float[] severity,damage_vote;public PhysicsInfo physics; }
    [Serializable] public class Summary { public float stiffness_index,max_displacement_mm,max_stress_mpa; public int active_sensors,sensor_capacity; }
    [Serializable] public class Observability { public int rank,unknowns; }
    [Serializable] public class Excitation { public int case_count,active_observations; public string protocol,display_case; public Observability observability; }
    [Serializable] public class BridgeSettings { public float vehicle_position_m=12,front_axle_kn=80,rear_axle_kn=120,axle_spacing_m=4,lane_offset_m=0,deck_load_kn_m=10,wind_total_kn=50; }
    [Serializable] public class BridgeCurrent { public float deck_down_mm,left_reaction_kn,right_reaction_kn,vertical_balance_error_kn; }
    [Serializable] public class BridgeSweep { public float peak_down_mm,critical_front_x_m;public float[] member_min_axial_kn,member_max_axial_kn; }
    [Serializable] public class BridgeVehicle { public float front_x,rear_x,lane_z;public bool visible; }
    [Serializable] public class BridgeResponse { public BridgeCurrent current;public BridgeSweep sweep;public BridgeVehicle vehicle; }
    [Serializable] public class TwinResponse { public BridgeResponse bridge; public int dimension; public string model_id,model_name; public Node[] nodes; public Member[] members; public Support[] supports; public Load[] loads; public Sensor[] sensors; public Prediction prediction; public Summary summary; public Excitation excitation; }
    [Serializable] private class Request { public BridgeSettings bridge;public float[] damage; public float load_scale=1; public int sensor_count=38; public float noise=.005f; public bool physics; public string protocol,display_case,refinement,model_id; }

    private void Start()
    {
        if(!startIn3D){modelId="planar";loss=new float[21];selected=13;sensorBudget=sensorCapacity=38;yaw=-18;}
        loss[selected] = .3f;
        viewCamera = Camera.main;
        if (viewCamera == null) { var c = new GameObject("Twin Camera"); viewCamera = c.AddComponent<Camera>(); c.tag="MainCamera"; }
        viewCamera.clearFlags = CameraClearFlags.SolidColor;
        viewCamera.backgroundColor = new Color(.045f,.065f,.1f);
        viewCamera.nearClipPlane = .1f; viewCamera.farClipPlane = 300;
        RenderSettings.ambientLight = new Color(.55f,.63f,.72f);
        var light = new GameObject("Twin Key Light").AddComponent<Light>();
        light.type=LightType.Directional; light.intensity=1.2f; light.transform.rotation=Quaternion.Euler(45,-30,0);
        UpdateCamera(); StartCoroutine(Analyze());
    }

    private IEnumerator Analyze()
    {
        if (busy) yield break;
        busy=true; sceneBuilt=false; message="Solving FEM and estimating damage…";
        var payload=new Request { model_id=modelId, bridge=modelId=="bridge"?bridgeSettings:null, damage=(float[])loss.Clone(), physics=physics, sensor_count=sensorBudget,
            noise=sensorNoise,refinement=noiseAware?"sparse":"legacy",
            protocol=multipleLoads?"multi":"single",display_case=multipleLoads?"LC"+(displayCase+1):"LC1" };
        using (var request=new UnityWebRequest(apiUrl.TrimEnd('/')+"/api/analyze", "POST"))
        {
            request.uploadHandler=new UploadHandlerRaw(Encoding.UTF8.GetBytes(JsonUtility.ToJson(payload)));
            request.downloadHandler=new DownloadHandlerBuffer(); request.timeout=60;
            request.SetRequestHeader("Content-Type","application/json");
            yield return request.SendWebRequest();
            if (request.result!=UnityWebRequest.Result.Success) message="API error: "+request.error+" — Start Python server on "+apiUrl;
            else
            {
                try
                {
                    var response=JsonUtility.FromJson<TwinResponse>(request.downloadHandler.text);
                    if (response.nodes==null || response.members==null) throw new Exception("Invalid twin response");
                    data=response; sensorCapacity=response.summary.sensor_capacity; Rebuild(); sceneBuilt=true; message="Analysis complete · simulated structure";
                }
                catch (Exception error) { message=error.Message;Debug.LogError("Twin analysis/render failed: "+error); }
            }
        }
        busy=false;
    }

    private void SwitchModel(bool space) { SwitchModelId(space?"space":"planar"); }
    private void SwitchModelId(string next)
    {
        if(busy)return;
        bool spatial=next!="planar";modelId=next;loss=new float[spatial?78:21];selected=spatial?4:13;
        if(next!="bridge")loss[selected]=.3f;
        sensorBudget=sensorCapacity=next=="bridge"?131:spatial?132:38;physics=false;estimatedDamage=false;
        displayCase=next=="bridge"?1:0;multipleLoads=true;bridgeSettings=new BridgeSettings();
        yaw=spatial?-32:-18;distance=32;data=null;
        if(geometry!=null)Destroy(geometry);
        UpdateCamera();StartCoroutine(Analyze());
    }

    private Vector3 Point(int i)
    {
        var n=data.nodes[i]; return new Vector3(n.x, n.y, n.z)+(deformed?new Vector3(n.ux,n.uy,n.uz)*deformationScale:Vector3.zero);
    }
    private Material MakeMaterial(Color color)
    {
        var shader=Shader.Find("Standard") ?? Shader.Find("Universal Render Pipeline/Lit") ?? Shader.Find("Sprites/Default");
        var mat=new Material(shader); mat.color=color; ownedMaterials.Add(mat); return mat;
    }
    private GameObject Primitive(PrimitiveType type, string label, Vector3 position, Vector3 scale, Color color)
    {
        var obj=GameObject.CreatePrimitive(type); obj.name=label; obj.transform.SetParent(geometry.transform,false);
        obj.transform.position=position; obj.transform.localScale=scale; obj.GetComponent<Renderer>().sharedMaterial=MakeMaterial(color); return obj;
    }
    private GameObject Rod(string label, Vector3 a, Vector3 b, float radius, Color color)
    {
        var rod=Primitive(PrimitiveType.Cylinder,label,(a+b)*.5f,new Vector3(radius,(b-a).magnitude*.5f,radius),color);
        rod.transform.up=(b-a).normalized; return rod;
    }
    private Color MemberColor(Member m)
    {
        if (stressView) return Color.Lerp(new Color(.22f,.6f,.55f),m.stress<0?new Color(.4f,.65f,1):new Color(1,.4f,.4f),Mathf.Clamp01(Mathf.Abs(m.stress)/100e6f));
        if(estimatedDamage && (data.prediction==null || !data.prediction.available)) return Color.gray;
        float severity=estimatedDamage?data.prediction.severity[m.id]:m.damage;
        return severity>.5f?new Color(.94f,.4f,.4f):severity>(estimatedDamage?.05f:.001f)?new Color(.9f,.72f,.32f):new Color(.27f,.68f,.62f);
    }
    private void Rebuild()
    {
        if (geometry!=null) Destroy(geometry);
        foreach(var mat in ownedMaterials) Destroy(mat);
        ownedMaterials.Clear();foreach(var mesh in ownedMeshes)Destroy(mesh);ownedMeshes.Clear(); rods.Clear(); joints.Clear();
        geometry=new GameObject("Twin Geometry");
        foreach(var member in data.members)
        {
            var color=MemberColor(member); if(member.id==selected) color=Color.Lerp(color,Color.white,.35f);
            rods.Add(Rod("Member "+member.id,Point(member.a),Point(member.b),member.id==selected?.19f:.12f,color));
        }
        foreach(var node in data.nodes) joints.Add(Primitive(PrimitiveType.Sphere,"Node "+node.id,Point(node.id),Vector3.one*.23f,new Color(.65f,.77f,.8f)));
        foreach(var support in data.supports)
        {
            var p=Point(support.node);
            Primitive(PrimitiveType.Cube,support.type+" support",p+Vector3.down*.36f,new Vector3(.7f,.38f,.7f),new Color(.3f,.4f,.5f));
            if(support.type=="roller") Primitive(PrimitiveType.Sphere,"Roller",p+Vector3.down*.67f,new Vector3(.35f,.25f,.35f),new Color(.6f,.68f,.75f));
        }
        if(IsBridge && data.bridge!=null)BuildBridge();
        if(showLoads) foreach(var load in data.loads)
        {
            var p=Point(load.node); var direction=new Vector3(load.fx,load.fy,load.fz).normalized;var end=p+direction*1.8f;
            var side=Vector3.Cross(direction,Mathf.Abs(direction.y)<.9f?Vector3.up:Vector3.forward).normalized;
            Rod("Load",p+direction*.3f,end,.045f,new Color(.66f,.59f,1));
            Rod("Arrow",end,end-direction*.4f-side*.25f,.045f,new Color(.66f,.59f,1));
            Rod("Arrow",end,end-direction*.4f+side*.25f,.045f,new Color(.66f,.59f,1));
        }
        if(showSensors) foreach(var sensor in data.sensors)
        {
            if(!sensor.active) continue;
            Vector3 p=sensor.kind=="strain"?(Point(data.members[sensor.member].a)+Point(data.members[sensor.member].b))*.5f:Point(sensor.node)+Vector3.forward*.18f;
            Primitive(PrimitiveType.Sphere,sensor.id,p,Vector3.one*.13f,new Color(.7f,1,.83f));
        }
        for(int i=-4;i<=28;i+=2) Rod("Grid",new Vector3(i,-1,-10),new Vector3(i,-1,10),.012f,new Color(.12f,.18f,.26f));
        for(int i=-10;i<=10;i+=2) Rod("Grid",new Vector3(-4,-1,i),new Vector3(28,-1,i),.012f,new Color(.12f,.18f,.26f));
    }

    private void UpdateCamera()
    {
        var centre=new Vector3(12,1.5f,0); var rotation=Quaternion.Euler(pitch,yaw,0);
        viewCamera.transform.position=centre+rotation*new Vector3(0,0,-distance); viewCamera.transform.LookAt(centre);
    }
    private void Update()
    {
        if(viewCamera==null) return;
        bool overControls=Input.mousePosition.x<310 || Input.mousePosition.x>Screen.width-300;
        if(Input.GetMouseButtonDown(0)) { down=Input.mousePosition; maxDrag=0; }
        if(Input.GetMouseButton(0)&&!overControls)
        {
            maxDrag=Mathf.Max(maxDrag,Vector2.Distance(down,Input.mousePosition));
            yaw+=Input.GetAxis("Mouse X")*3; pitch=Mathf.Clamp(pitch-Input.GetAxis("Mouse Y")*3,-65,65); UpdateCamera();
        }
        if(!overControls) { distance=Mathf.Clamp(distance-Input.mouseScrollDelta.y*2,10,90); UpdateCamera(); }
        if(Input.GetMouseButtonUp(0)&&maxDrag<5&&!overControls&&data!=null)
        {
            if(Physics.Raycast(viewCamera.ScreenPointToRay(Input.mousePosition),out RaycastHit hit))
            {
                var name=hit.collider.gameObject.name;
                if(name.StartsWith("Member ")&&int.TryParse(name.Substring(7),out int id)) { selected=id; Rebuild(); }
            }
        }
        if(Input.GetKeyDown(KeyCode.Return)&&!busy) StartCoroutine(Analyze());
    }

    private void OnGUI()
    {
        GUI.color=Color.white;
        GUILayout.BeginArea(new Rect(16,16,278,Screen.height-32),GUI.skin.box);
        controlsScroll=GUILayout.BeginScrollView(controlsScroll);
        GUILayout.Label("STRATUM / STRUCTURAL TWIN"); GUILayout.Space(10);
        GUILayout.Label("Python FEM → Sensors → ML → Unity"); GUILayout.Space(14);
        GUILayout.Label("API URL"); apiUrl=GUILayout.TextField(apiUrl);
        if(data!=null)
        {
            GUILayout.Space(14); GUILayout.Label("Configured stiffness index: "+data.summary.stiffness_index.ToString("F1")+"%");
            GUILayout.Label("Peak displacement: "+data.summary.max_displacement_mm.ToString("F2")+" mm");
            GUILayout.Label("Active sensors: "+data.summary.active_sensors+" / "+data.summary.sensor_capacity);
            if(data.excitation!=null)GUILayout.Label("Rank: "+data.excitation.observability.rank+"/"+data.excitation.observability.unknowns+" · "+data.excitation.active_observations+" observations");
        }
        GUILayout.Space(12);
        GUI.enabled=!busy;
        if(GUILayout.Button("Structure: "+modelId+" ▾ (cycle)"))SwitchModelId(modelId=="space"?"bridge":modelId=="bridge"?"planar":"space");
        GUI.enabled=true;
        GUILayout.Label(modelId=="planar"?"Planar FEM / validated inference study":modelId=="bridge"?"Bridge FEM / static vehicle loading":"3D FEM / virtual sensing · ML training pending");
        if(modelId=="bridge")BridgeControls();
        GUI.enabled=modelId!="bridge";
        multipleLoads=GUILayout.Toggle(multipleLoads,"Combine three load cases");
        GUI.enabled=true;
        if(multipleLoads)displayCase=GUILayout.SelectionGrid(displayCase,modelId=="bridge"?new[]{"LC1 dead","LC2 dead + vehicle","LC3 dead + wind"}:modelId=="space"?new[]{"LC1 vertical","LC2 eccentric","LC3 X/Z wind"}:new[]{"LC1 vertical","LC2 asym.","LC3 lateral"},1);
        GUILayout.Label("Physical sensor budget: "+sensorBudget);
        sensorBudget=Mathf.RoundToInt(GUILayout.HorizontalSlider(sensorBudget,1,sensorCapacity));
        GUILayout.Label("Same sensors reused; damage fixed across tests.");
        GUILayout.Space(20); GUILayout.Label("Selected: M"+(selected+1).ToString("D2"));
        if(GUILayout.Button("Previous member")) { selected=(selected+loss.Length-1)%loss.Length; if(data!=null)Rebuild(); }
        if(GUILayout.Button("Next member")) { selected=(selected+1)%loss.Length; if(data!=null)Rebuild(); }
        GUILayout.Label("Configured stiffness loss: "+(loss[selected]*100).ToString("F0")+"%");
        loss[selected]=GUILayout.HorizontalSlider(loss[selected],0,.8f);
        GUI.enabled=modelId=="planar";
        physics=GUILayout.Toggle(physics,"Physics inverse refinement");
        noiseAware=GUILayout.Toggle(noiseAware,"Use noise-aware sparse method (≤2 members)");
        GUI.enabled=true;
        GUILayout.Label("Normalized measurement noise σ: "+(sensorNoise*100).ToString("F1")+"%");
        sensorNoise=GUILayout.HorizontalSlider(sensorNoise,0,.05f);
        GUI.enabled=!busy;
        if(GUILayout.Button("Run analysis [Enter]")) StartCoroutine(Analyze());
        if(GUILayout.Button("Reset healthy")) { Array.Clear(loss,0,loss.Length); StartCoroutine(Analyze()); }
        GUI.enabled=true; GUILayout.Space(18);
        bool s=GUILayout.Toggle(stressView,"Color by axial stress");
        bool ed=GUILayout.Toggle(estimatedDamage,"Color damage by ML estimate");
        bool d=GUILayout.Toggle(deformed,"Show deformed geometry");
        bool l=GUILayout.Toggle(showLoads,"Show loads"), se=GUILayout.Toggle(showSensors,"Show sensors");
        float ds=GUILayout.HorizontalSlider(deformationScale,0,500);
        GUILayout.Label("Deformation magnification: "+ds.ToString("F0")+"×");
        if(s!=stressView||ed!=estimatedDamage||d!=deformed||l!=showLoads||se!=showSensors||Mathf.Abs(ds-deformationScale)>.5f)
        { stressView=s; estimatedDamage=ed; deformed=d; showLoads=l; showSensors=se; deformationScale=ds; if(data!=null)Rebuild(); }
        GUILayout.Space(14); GUILayout.Label(message); GUILayout.EndScrollView();GUILayout.EndArea();
        if(data==null) return;
        var m=data.members[selected]; var p=data.prediction;
        GUILayout.BeginArea(new Rect(Screen.width-292,16,276,Mathf.Min(Screen.height-32,650)),GUI.skin.box);
        GUILayout.Label("MEMBER "+m.name); GUILayout.Space(12);
        GUILayout.Label("Length: "+m.length.ToString("F2")+" m"); GUILayout.Label("Area: "+m.area.ToString("F3")+" m²");
        GUILayout.Label("Effective E: "+(m.effective_modulus/1e9f).ToString("F0")+" GPa");
        GUILayout.Label("Axial stress: "+(m.stress/1e6f).ToString("F2")+" MPa");
        GUILayout.Label("Axial strain: "+(m.strain*1e6f).ToString("F1")+" με");
        GUILayout.Label("Axial force: "+(m.axial_force/1000).ToString("F1")+" kN"); GUILayout.Space(20);
        if(IsBridge && data.bridge!=null)
        {
            var bridge=data.bridge;
            GUILayout.Label("BRIDGE RESPONSE");
            GUILayout.Label("Deck down: "+bridge.current.deck_down_mm.ToString("F2")+" mm");
            GUILayout.Label("Abutment Y: "+bridge.current.left_reaction_kn.ToString("F1")+" / "+bridge.current.right_reaction_kn.ToString("F1")+" kN");
            GUILayout.Label("Sweep peak: "+bridge.sweep.peak_down_mm.ToString("F2")+" mm at x="+bridge.sweep.critical_front_x_m.ToString("F2")+" m");
            GUILayout.Label("Member axial envelope: "+bridge.sweep.member_min_axial_kn[selected].ToString("F1")+" to "+bridge.sweep.member_max_axial_kn[selected].ToString("F1")+" kN");
            GUILayout.Label("Static research vehicle; idealized deck load transfer. No slab bending, impact or code capacity checks.");
        }
        GUILayout.Label("DAMAGE ESTIMATE");
        if(p!=null&&p.available)
        {
            GUILayout.Label("Estimated loss: "+(p.severity[selected]*100).ToString("F1")+"%");
            GUILayout.Label("Forest vote: "+(p.damage_vote[selected]*100).ToString("F0")+"% (uncalibrated)");
            GUILayout.Label(p.method);
            if(p.physics!=null&&p.physics.method=="Noise-aware sparse physics")
                GUILayout.Label("Noise σ: "+(p.physics.noise_std*100).ToString("F1")+"% · estimated offset: "+(p.physics.estimated_common_bias*100).ToString("F2")+"%");
        }
        else GUILayout.Label(p==null?"No prediction":p.reason);
        GUILayout.Space(15); GUILayout.Label("Research prototype. No safety rating. Buckling and nonlinear effects excluded.");
        GUILayout.EndArea();
        GUI.Label(new Rect(320,Screen.height-40,Screen.width-640,30),"Drag: orbit  ·  Scroll: zoom  ·  Click a member: inspect");
    }
    private void BridgeControls()
    {
        GUILayout.Label("STATIC RESEARCH VEHICLE");
        GUILayout.Label("Front axle x: "+bridgeSettings.vehicle_position_m.ToString("F2")+" m");
        bridgeSettings.vehicle_position_m=GUILayout.HorizontalSlider(bridgeSettings.vehicle_position_m,0,24+bridgeSettings.axle_spacing_m);
        GUILayout.Label("Front / rear axle kN: "+bridgeSettings.front_axle_kn.ToString("F0")+" / "+bridgeSettings.rear_axle_kn.ToString("F0"));
        bridgeSettings.front_axle_kn=GUILayout.HorizontalSlider(bridgeSettings.front_axle_kn,0,250);
        bridgeSettings.rear_axle_kn=GUILayout.HorizontalSlider(bridgeSettings.rear_axle_kn,0,250);
        GUILayout.Label("Axle spacing: "+bridgeSettings.axle_spacing_m.ToString("F1")+" m");
        bridgeSettings.axle_spacing_m=GUILayout.HorizontalSlider(bridgeSettings.axle_spacing_m,2,8);
        bridgeSettings.vehicle_position_m=Mathf.Min(bridgeSettings.vehicle_position_m,24+bridgeSettings.axle_spacing_m);
        GUILayout.Label("Lane offset: "+bridgeSettings.lane_offset_m.ToString("F1")+" m");
        bridgeSettings.lane_offset_m=GUILayout.HorizontalSlider(bridgeSettings.lane_offset_m,-1.2f,1.2f);
        GUILayout.Label("Deck line load: "+bridgeSettings.deck_load_kn_m.ToString("F1")+" kN/m");
        bridgeSettings.deck_load_kn_m=GUILayout.HorizontalSlider(bridgeSettings.deck_load_kn_m,0,30);
        GUILayout.Label("Transverse wind: "+bridgeSettings.wind_total_kn.ToString("F0")+" kN");
        bridgeSettings.wind_total_kn=GUILayout.HorizontalSlider(bridgeSettings.wind_total_kn,0,200);
    }
    private Vector3 BridgePoint(float x,float z,float height)
    {
        float xc=Mathf.Clamp(x,0,24),t=(xc-6*Mathf.Min((int)(xc/6),3))/6,right=(z+2)/4;
        int bay=Mathf.Min((int)(xc/6),3);Vector3 shift=Vector3.zero;
        for(int station=0;station<2;station++)for(int side=0;side<2;side++)
        {
            int i=4*(bay+station)+side;var n=data.nodes[i];
            shift+=(Point(i)-new Vector3(n.x,n.y,n.z))*(station==0?1-t:t)*(side==0?1-right:right);
        }
        return new Vector3(x,height,z)+shift;
    }
    private void BuildBridge()
    {
        foreach(float x in new[]{0f,24f})Primitive(PrimitiveType.Cube,"Abutment",new Vector3(x,-.85f,0),new Vector3(1.3f,.8f,5),new Color(.5f,.57f,.53f));
        for(int i=0;i<4;i++)
        {
            var road=new GameObject("Idealized deck panel");road.transform.SetParent(geometry.transform,false);
            var mesh=new Mesh();mesh.vertices=new[]{BridgePoint(6*i,-2,.08f),BridgePoint(6*i,2,.08f),BridgePoint(6*(i+1),2,.08f),BridgePoint(6*(i+1),-2,.08f)};
            mesh.triangles=new[]{0,1,2,0,2,3};mesh.RecalculateNormals();ownedMeshes.Add(mesh);
            road.AddComponent<MeshFilter>().sharedMesh=mesh;road.AddComponent<MeshRenderer>().sharedMaterial=MakeMaterial(new Color(.55f,.59f,.54f));
        }
        var v=data.bridge.vehicle;if(!v.visible)return;
        Primitive(PrimitiveType.Cube,"Research truck cargo",BridgePoint((v.front_x+v.rear_x)/2-.5f,v.lane_z,.95f),new Vector3(v.front_x-v.rear_x,.95f,1.4f),new Color(.72f,.5f,.23f));
        Primitive(PrimitiveType.Cube,"Research truck cab",BridgePoint(v.front_x+.1f,v.lane_z,.88f),new Vector3(1.1f,.9f,1.4f),new Color(.25f,.5f,.48f));
        foreach(float x in new[]{v.front_x,v.rear_x})foreach(float dz in new[]{-.76f,.76f})Primitive(PrimitiveType.Sphere,"Wheel",BridgePoint(x,v.lane_z+dz,.28f),new Vector3(.5f,.5f,.25f),new Color(.2f,.25f,.2f));
    }
    private void OnDestroy() { foreach(var mesh in ownedMeshes)if(mesh!=null)Destroy(mesh); foreach(var mat in ownedMaterials) if(mat!=null)Destroy(mat); }
}
