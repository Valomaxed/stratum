"""Reproducible independent OpenSees comparison and dt/2, dt/4 study.

Usage: python -m twin.seismic_benchmark --opensees-python <Python 3.12 exe>
OpenSees is optional and executes only in a separate verification process.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import numpy as np
import scipy
from .seismic import G, SYSTEMS, LABELS, settings, build_frame, parse_at2, frame_history

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT/'data/seismic-validation'
SOURCES = ('twin/seismic.py','twin/dynamics.py','twin/opensees_reference.py',
           'twin/seismic_benchmark.py','web/records/el-centro-1940.at2')
LIMITS = dict(frequency_relative=1e-7, history_normalized_max=1e-6,
              peak_relative=1e-6, reference_force_balance=1e-7,
              production_to_quarter_peak_relative=.01,
              half_to_quarter_peak_relative=.0025,
              history_convergence_ratio_min=3.,history_convergence_ratio_max=5.)


def source_hashes():
    return {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in SOURCES}


def saved_report(path=None):
    """No saved PASS survives a change to solver, record or benchmark sources."""
    path = REPORT_DIR/'report.json' if path is None else Path(path)
    if not path.is_file(): return dict(available=False,reason='Independent benchmark has not been run.')
    try:
        report=json.loads(path.read_text(encoding='utf8'))
        fresh=report['source_hashes']==source_hashes()
        if report.get('schema_version') != 1: raise ValueError('Unknown report schema')
        if type(report['passed']) is not bool or not report['comparisons'] or not report['convergence']:
            raise ValueError('Incomplete report')
        computed_pass=all(row['passed'] is True for row in report['comparisons']+report['convergence'])
        if computed_pass != report['passed']: raise ValueError('Inconsistent report result')
    except (OSError,ValueError,KeyError,TypeError):
        return dict(available=False,reason='Saved benchmark report is unreadable or incompatible.')
    return report | dict(available=True,fresh=fresh,
        current_pass=bool(fresh and report['passed']),
        freshness_note='Numerical source and record hashes match.' if fresh else 'Numerical sources or record changed; rerun verification.')


def relative_error(observed, reference):
    observed,reference=np.asarray(observed,float),np.asarray(reference,float)
    error=np.abs(observed-reference)
    return dict(normalized_max=float(error.max()/max(np.abs(reference).max(),1e-14)),
                normalized_l2=float(np.linalg.norm(error)/max(np.linalg.norm(reference),1e-14)),
                absolute_max=float(error.max()))


def compare_reference(stratum, reference):
    history=stratum['history']
    actual_u=np.asarray(history['floor_displacement_mm'])/1000
    actual_time=np.asarray(history['time_s'])
    reference_time=np.asarray(reference['time_s'])
    if actual_time.shape != reference_time.shape or not np.allclose(actual_time,reference_time,rtol=0,atol=1e-10):
        raise ValueError('Reference histories must use the same integration grid')
    frequency=np.abs(np.asarray(stratum['frequencies_hz'])/reference['frequencies_hz']-1)
    errors=dict(frequency_max_relative=float(frequency.max()),
        floor_displacement_m=relative_error(actual_u,reference['displacement_m']),
        base_shear_kn=relative_error(history['base_shear_kn'],reference['base_shear_kn']),
        roof_absolute_acceleration_m_s2=relative_error(history['roof_absolute_acceleration_m_s2'],
            np.asarray(reference['relative_acceleration_m_s2'])[:,-1]+np.asarray(history['ground_g'])*G))
    peak_map={'drift_pct':'peak_drift_pct','roof_mm':'peak_roof_mm','base_shear_kn':'peak_base_shear_kn'}
    peaks={key:dict(stratum=stratum[value],opensees=reference['peaks'][key],
                   relative_error=abs(stratum[value]-reference['peaks'][key])/max(abs(reference['peaks'][key]),1e-14))
           for key,value in peak_map.items()}
    passed=(errors['frequency_max_relative'] <= LIMITS['frequency_relative']
        and all(errors[key]['normalized_max'] <= LIMITS['history_normalized_max']
                for key in ('floor_displacement_m','base_shear_kn','roof_absolute_acceleration_m_s2'))
        and all(p['relative_error'] <= LIMITS['peak_relative'] for p in peaks.values())
        and reference['support_and_damper_balance_error'] <= LIMITS['reference_force_balance'])
    return dict(passed=bool(passed),errors=errors,peaks=peaks,
                force_balance_error=reference['support_and_damper_balance_error'])


def convergence(frame, record, baseline):
    # Offline verification may refine beyond the unchanged 60000-step API cap.
    half=frame_history(frame,record,time_step_divisor=2,full_history=True,step_limit=240000)
    quarter=frame_history(frame,record,time_step_divisor=4,full_history=True,step_limit=240000)
    keys=('peak_drift_pct','peak_roof_mm','peak_base_shear_kn')
    peaks={key:dict(production=baseline[key],half=half[key],quarter=quarter[key],
          production_to_quarter_relative=abs(baseline[key]-quarter[key])/max(abs(quarter[key]),1e-14),
          half_to_quarter_relative=abs(half[key]-quarter[key])/max(abs(quarter[key]),1e-14)) for key in keys}
    u0=np.asarray(baseline['history']['floor_displacement_mm'])
    u1=np.asarray(half['history']['floor_displacement_mm'])[::2]
    u2=np.asarray(quarter['history']['floor_displacement_mm'])[::4]
    e0,e1=np.linalg.norm(u0-u1),np.linalg.norm(u1-u2)
    ratio=float(e0/e1) if e1>1e-14 else None
    passed=(all(p['production_to_quarter_relative']<=LIMITS['production_to_quarter_peak_relative']
                and p['half_to_quarter_relative']<=LIMITS['half_to_quarter_peak_relative'] for p in peaks.values())
            and ratio is not None and LIMITS['history_convergence_ratio_min'] <= ratio <= LIMITS['history_convergence_ratio_max'])
    return dict(passed=bool(passed),time_steps_s=[r['integration']['dt_s'] for r in (baseline,half,quarter)],
                step_counts=[r['integration']['steps'] for r in (baseline,half,quarter)],
                history_difference_ratio=ratio,peaks=peaks),half,quarter


def cases():
    record=parse_at2((ROOT/'web/records/el-centro-1940.at2').read_text(encoding='utf8'),name='El Centro 1940 N–S (Peknold)')
    yield 'el-centro-default-4-story',settings(),record,1.
    time=np.arange(201)*.01
    # Explicit synthetic QA signals: these are not additional earthquake records.
    motion=dict(npts=len(time),dt=.01,acceleration=G*.08*np.sin(2*np.pi*1.7*time)*np.sin(np.pi*time/2)**2,
                name='Synthetic QA pulse, zero first sample',input_unit='m/s2')
    yield 'synthetic-2-story-undamped',settings(dict(stories=2,story_height_m=3.6,bay_width_m=4.,floor_mass_t=80.,
        damping_ratio=0.,column_inertia_cm4=40000.,beam_inertia_cm4=18000.)),motion,1.7
    motion=dict(npts=len(time),dt=.01,acceleration=G*(.035*np.cos(2*np.pi*.8*time)+.015*np.sin(2*np.pi*3*time)),
                name='Synthetic QA signal, nonzero first sample',input_unit='m/s2')
    yield 'synthetic-8-story-damped',settings(dict(stories=8,story_height_m=2.8,bay_width_m=7.5,floor_mass_t=25.,
        damping_ratio=.1,brace_area_mm2=3500.,column_area_mm2=15000.,beam_area_mm2=10000.,
        column_inertia_cm4=30000.,beam_inertia_cm4=16000.)),motion,.65


def write_markdown(report, path):
    lines=['# Stratum seismic solver verification','',
        f"Generated: {report['generated_at_utc']}", '',
        f"Overall result: **{'PASS' if report['passed'] else 'FAIL'}**. "
        f"{sum(c['passed'] for c in report['comparisons'])}/{len(report['comparisons'])} independent comparisons; "
        f"{sum(c['passed'] for c in report['convergence'])}/3 time-step studies.", '',
        '## Independent implementation','',
        'OpenSees independently assembles elasticBeamColumn and axial Truss elements, applies fixed supports and '
        'horizontal equalDOF floor constraints, and retains its full massless vertical/rotation DOFs. '
        'It receives physical parameters and SI acceleration samples; it does not receive Stratum stiffness/mass '
        'matrices, connectivity, eigenvectors, damping coefficients or calculated response. Both engines '
        'use Newmark average acceleration and the same time grid, so this verifies implementation consistency '
        'rather than comparing different integration methods. All finite floor modes are compared.', '',
        'The real earthquake is the bundled 31.16 s El Centro 1940 N–S Peknold example (1559 samples, DT=0.02 s). '
        'Two additional synthetic QA signals exercise 2- and 8-story models, changed sections/masses/geometry, '
        'zero and nonzero initial acceleration, 0% and 10% damping, and amplitude factors 1.7 and 0.65. '
        'They are verification fixtures, not an earthquake suite.', '',
        'A nonzero first sample is retained. OpenSees initial relative accelerations, including massless DOFs, '
        'are recovered from its own complete eigenbasis and committed before integration; no leading zero '
        'or time shift is introduced. Rayleigh damping targets the first two independently calculated modes. '
        'Brace Rayleigh damping is explicitly enabled.', '',
        f"Reference engine: OpenSees {report['engine']['version']}, OpenSeesPy {report['engine']['openseespy']}, "
        f"Python {report['engine']['python']}. Stratum runtime: Python {report['stratum_runtime']['python']}, "
        f"NumPy {report['stratum_runtime']['numpy']}, SciPy {report['stratum_runtime']['scipy']}.", '',
        '## Full-history comparison','',
        '| Case | System | Max frequency error (%) | Floor displacement history error (%) | Base shear history error (%) | Result |',
        '|---|---|---:|---:|---:|---|']
    for c in report['comparisons']:
        e=c['errors']
        lines.append(f"| {c['case']} | {LABELS[c['system']]} | {100*e['frequency_max_relative']:.3g} | "
            f"{100*e['floor_displacement_m']['normalized_max']:.3g} | {100*e['base_shear_kn']['normalized_max']:.3g} | {'PASS' if c['passed'] else 'FAIL'} |")
    lines += ['', 'History error is maximum absolute pointwise difference divided by the maximum absolute reference '
        'amplitude, over every integration sample (not a pointwise percentage near zero crossings). '
        'Roof absolute acceleration and drift/roof/shear peaks are also checked in the machine report.', '',
        '## Time-step convergence: full El Centro record','',
        '| System | dt / dt2 / dt4 (s) | Drift change, dt→dt4 (%) | Roof change (%) | Shear change (%) | History error ratio | Result |',
        '|---|---|---:|---:|---:|---:|---|']
    for c in report['convergence']:
        p=c['peaks']
        lines.append(f"| {LABELS[c['system']]} | {' / '.join(f'{dt:.6g}' for dt in c['time_steps_s'])} | "
            f"{100*p['peak_drift_pct']['production_to_quarter_relative']:.4f} | "
            f"{100*p['peak_roof_mm']['production_to_quarter_relative']:.4f} | "
            f"{100*p['peak_base_shear_kn']['production_to_quarter_relative']:.4f} | "
            f"{c['history_difference_ratio']:.3f} | {'PASS' if c['passed'] else 'FAIL'} |")
    lines += ['', 'The convergence ratio is ‖u(dt)−u(dt/2)‖ / ‖u(dt/2)−u(dt/4)‖ with all floor histories '
        'compared on the original grid. A value near four is consistent with second-order integration. '
        'Peaks are evaluated on each run’s full grid. This is a refinement check, not an exact-solution error bound.', '',
        '## Predeclared acceptance criteria','',
        '- Relative modal-frequency error ≤ 1e-7; normalized maximum history and relative peak errors ≤ 1e-6.',
        '- Independent OpenSees support/damping force-balance error ≤ 1e-7.',
        '- Current-step versus quarter-step drift/roof/shear peak changes ≤ 1%; half versus quarter ≤ 0.25%.',
        '- Floor-history refinement ratio between 3 and 5.', '',
        '## Base shear convention','',
        'Both compare generalized base shear demand V = −Σ m(a_relative + ag), equivalent to Stratum’s '
        'Σ(Ku + Cv). OpenSees separately recovers column-base support forces including stiffness-proportional '
        'damping. Its mass-proportional nodal dampers are not column elements, so their forces are added '
        'when checking support-plus-damper equilibrium. Raw support shear and nodal damping contributions '
        'are retained in the trace archive. Generalized demand is not solely the elastic column-end shear.', '',
        '## Scope and reproducibility','',
        'These results verify the stated elastic idealization and the exercised configurations. They do not '
        'validate yielding, buckling, gravity/P–Delta, soil interaction, connection behavior, a real building '
        'or code compliance. The real-record study covers one example earthquake, not a hazard-selected suite. '
        'Source hashes and the raw input accelerogram identify this run; the app marks the saved report stale '
        'when numerical source or record hashes change.', '',
        'Run: `python -m twin.seismic_benchmark --opensees-python work/opensees-venv/Scripts/python.exe`.', '',
        'References: [OpenSees elasticBeamColumn](https://openseespydoc.readthedocs.io/en/latest/src/elasticBeamColumn.html), '
        '[equalDOF](https://openseespydoc.readthedocs.io/en/latest/src/equalDOF.html), '
        '[Truss Rayleigh option](https://openseespydoc.readthedocs.io/en/latest/src/trussEle.html), '
        '[Path time series](https://openseespydoc.readthedocs.io/en/latest/src/pathTs.html), '
        '[setNodeAccel](https://openseespydoc.readthedocs.io/en/latest/src/setNodeAccel.html).', '']
    path.write_text('\n'.join(lines),encoding='utf8')


def run(opensees_python, output_dir=None, make_figures=True):
    output=REPORT_DIR if output_dir is None else Path(output_dir)
    output.mkdir(parents=True,exist_ok=True)
    scratch=ROOT/'work/seismic-verification';scratch.mkdir(parents=True,exist_ok=True)
    comparisons, refinements, traces, default_data = [],[],{},{}
    engine=None
    with tempfile.TemporaryDirectory(prefix='run-',dir=scratch) as temp:
        temp=Path(temp)
        for case_id, config, record, scale in cases():
            for system in SYSTEMS:
                print(f'Checking {case_id} / {system}',flush=True)
                frame=build_frame(config,system)
                result=frame_history(frame,record,scale=scale,full_history=True)
                spec=dict(frame=config,system=system,record_dt_s=record['dt'],
                          acceleration_m_s2=record['acceleration'].tolist(),scale_factor=scale,
                          analysis_dt_s=result['integration']['dt_s'])
                request,response=temp/'input.json',temp/'output.json'
                request.write_text(json.dumps(spec,allow_nan=False),encoding='utf8')
                process=subprocess.run([str(Path(opensees_python).resolve()),str(ROOT/'twin/opensees_reference.py'),
                                        str(request),str(response)],capture_output=True,text=True,timeout=180)
                if process.returncode:
                    raise RuntimeError(f'OpenSees reference failed ({case_id}/{system}): {process.stderr[-2000:]}')
                reference=json.loads(response.read_text(encoding='utf8'));engine=reference['engine']
                comparison=compare_reference(result,reference)
                comparison.update(case=case_id,system=system,frame=config,scale_factor=scale,
                    record_name=record['name'],dt_s=result['integration']['dt_s'],samples=len(reference['time_s']),
                    frequencies_stratum_hz=result['frequencies_hz'],frequencies_opensees_hz=reference['frequencies_hz'],
                    rayleigh_stratum=[result['integration']['rayleigh_alpha'],result['integration']['rayleigh_beta']],
                    rayleigh_opensees=[reference['rayleigh_alpha'],reference['rayleigh_beta']],
                    reference_model=reference['model'],reference_stderr=process.stderr.strip())
                comparisons.append(comparison)
                prefix=case_id+'__'+system
                for key in ('time_s','displacement_m','relative_acceleration_m_s2','base_shear_kn',
                            'base_support_demand_kn','mass_damping_demand_kn'):
                    traces[prefix+'__opensees_'+key]=np.asarray(reference[key])
                for key,value in result['history'].items(): traces[prefix+'__stratum_'+key]=np.asarray(value)
                if case_id=='el-centro-default-4-story':
                    study,half,quarter=convergence(frame,record,result)
                    study['system']=system;refinements.append(study)
                    for name,value in (('half',half),('quarter',quarter)):
                        for key in ('time_s','floor_displacement_mm','base_shear_kn','roof_mm'):
                            traces[prefix+'__'+name+'_'+key]=np.asarray(value['history'][key])
                    default_data[system]=dict(stratum=result,opensees=reference,half=half,quarter=quarter)
        real_record=next(cases())[2]
        report=dict(schema_version=1,generated_at_utc=datetime.now(timezone.utc).isoformat(),
            passed=bool(all(c['passed'] for c in comparisons+refinements)),source_hashes=source_hashes(),
            engine=engine,stratum_runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),
            limits=LIMITS,comparisons=comparisons,convergence=refinements,
            reference_record={key:value for key,value in real_record.items() if key!='acceleration'} | {
                'original_at2':(ROOT/'web/records/el-centro-1940.at2').read_text(encoding='utf8')},
            default_frame=settings(),trace_archive='histories.npz',
            scope='Elastic implementation verification; not experimental validation, code assessment or an earthquake suite.')
        (output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf8')
        np.savez_compressed(output/'histories.npz',**traces)
        write_markdown(report,output/'report.md')
        # CSV retains every integration sample of the three real-record comparisons.
        import csv
        with (output/'el-centro-comparison.csv').open('w',newline='',encoding='utf8') as stream:
            writer=csv.writer(stream);writer.writerow(['system','time_s','stratum_roof_mm','opensees_roof_mm',
                'stratum_base_shear_kn','opensees_base_shear_kn','opensees_support_demand_kn','opensees_mass_damping_kn'])
            for system,data in default_data.items():
                s,o=data['stratum']['history'],data['opensees']
                for i,t in enumerate(s['time_s']):
                    writer.writerow([system,t,s['roof_mm'][i],o['displacement_m'][i][-1]*1000,
                        s['base_shear_kn'][i],o['base_shear_kn'][i],o['base_support_demand_kn'][i],o['mass_damping_demand_kn'][i]])
        if make_figures:
            subprocess.run([str(Path(opensees_python).resolve()),str(ROOT/'twin/seismic_benchmark_figures.py'),str(output.resolve())],check=True,timeout=120)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--opensees-python',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,default=REPORT_DIR)
    parser.add_argument('--no-figures',action='store_true')
    args=parser.parse_args()
    report=run(args.opensees_python,args.output_dir,not args.no_figures)
    print(json.dumps(dict(passed=report['passed'],comparisons=len(report['comparisons']),
                         convergence_studies=len(report['convergence']),report=str(args.output_dir/'report.md'))))
    if not report['passed']:sys.exit(1)


if __name__=='__main__':main()
