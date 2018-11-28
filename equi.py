#!/usr/bin/env python3

import os, sys, json, argparse, glob
import numpy as np

from lib.utils import create_path
from lib.utils import cvt_conf
from lib.water import compute_bonds
from lib.water import posi_diff
import lib.dump 

def _gen_lammps_input (conf_file, 
                       mass_map,
                       model,
                       nsteps,
                       dt,
                       ens,
                       temp,
                       pres = 1.0, 
                       tau_t = 0.1,
                       tau_p = 0.5,
                       prt_freq = 100, 
                       dump_freq = 1000) :
    ret = ''
    ret += 'clear\n'
    ret += '# --------------------- VARIABLES-------------------------\n'
    ret += 'variable        NSTEPS          equal %d\n' % nsteps
    ret += 'variable        THERMO_FREQ     equal %d\n' % prt_freq
    ret += 'variable        DUMP_FREQ       equal %d\n' % dump_freq
    ret += 'variable        TEMP            equal %f\n' % temp
    ret += 'variable        PRES            equal %f\n' % pres
    ret += 'variable        TAU_T           equal %f\n' % tau_t
    ret += 'variable        TAU_P           equal %f\n' % tau_p
    ret += '# ---------------------- INITIALIZAITION ------------------\n'
    ret += 'units           metal\n'
    ret += 'boundary        p p p\n'
    ret += 'atom_style      atomic\n'
    ret += '# --------------------- ATOM DEFINITION ------------------\n'
    ret += 'box             tilt large\n'
    ret += 'read_data       %s\n' % conf_file
    ret += 'change_box      all triclinic\n'
    for jj in range(len(mass_map)) :
        ret+= "mass            %d %f\n" %(jj+1, mass_map[jj])
    ret += '# --------------------- FORCE FIELDS ---------------------\n'
    ret += 'pair_style      deepmd %s\n' % model
    ret += 'pair_coeff\n'
    ret += '# --------------------- MD SETTINGS ----------------------\n'    
    ret += 'neighbor        1.0 bin\n'
    ret += 'timestep        %s\n' % dt
    ret += 'thermo          ${THERMO_FREQ}\n'
    if ens == 'nvt' :        
        ret += 'thermo_style    custom step ke pe etotal enthalpy temp press vol\n'
    elif 'npt' in ens :
        ret += 'thermo_style    custom step ke pe etotal enthalpy temp press vol\n'
    else :
        raise RuntimeError('unknow ensemble %s\n' % ens)                
    ret += 'dump            1 all custom ${DUMP_FREQ} dump.equi id type x y z vx vy vz\n'
    if ens == 'nvt' :
        ret += 'fix             1 all nvt temp ${TEMP} ${TEMP} ${TAU_T}\n'
    elif ens == 'npt-iso' or ens == 'npt':
        ret += 'fix             1 all npt temp ${TEMP} ${TEMP} ${TAU_T} iso ${PRES} ${PRES} ${TAU_P}\n'
    elif ens == 'npt-aniso' :
        ret += 'fix             1 all npt temp ${TEMP} ${TEMP} ${TAU_T} aniso ${PRES} ${PRES} ${TAU_P}\n'
    elif ens == 'npt-tri' :
        ret += 'fix             1 all npt temp ${TEMP} ${TEMP} ${TAU_T} tri ${PRES} ${PRES} ${TAU_P}\n'
    elif ens == 'nve' :
        ret += 'fix             1 all nve\n'
    else :
        raise RuntimeError('unknow ensemble %s\n' % ens)        
    ret += '# --------------------- INITIALIZE -----------------------\n'    
    ret += 'velocity        all create ${TEMP} %d\n' % (np.random.randint(0, 2**16))
    ret += '# --------------------- RUN ------------------------------\n'    
    ret += 'run             ${NSTEPS}\n'
    
    return ret

def make_task(iter_name, jdata, temp, pres) :
    equi_conf = jdata['equi_conf']
    equi_conf = os.path.abspath(equi_conf)
    model = jdata['model']
    model = os.path.abspath(model)
    model_mass_map = jdata['model_mass_map']
    nsteps = jdata['nsteps']
    dt = jdata['dt']
    stat_freq = jdata['stat_freq']
    dump_freq = jdata['dump_freq']
    ens = jdata['ens']
    tau_t = jdata['tau_t']
    tau_p = jdata['tau_p']

    if temp == None :
        temp = jdata['temp']
    elif 'temp' in jdata :
        print('T = %f overrides the temp in json data' % temp)
    jdata['temp'] = temp
    if 'npt' in ens :
        if pres == None :
            pres = jdata['pres']
        elif 'pres' in jdata :
            print('P = %f overrides the pres in json data' % pres)
        jdata['pres'] = pres    

    create_path(iter_name)
    cwd = os.getcwd()
    os.chdir(iter_name)
    with open('in.json', 'w') as fp:
        json.dump(jdata, fp, indent=4)
    os.symlink(os.path.relpath(equi_conf), 'conf.lmp')
    os.symlink(os.path.relpath(model), 'graph.pb')
    lmp_str \
        = _gen_lammps_input('conf.lmp',
                            model_mass_map, 
                            'graph.pb',
                            nsteps, 
                            dt, 
                            ens, 
                            temp,
                            pres, 
                            tau_t = tau_t,
                            tau_p = tau_p,
                            prt_freq = stat_freq, 
                            dump_freq = dump_freq)
    with open('in.lammps', 'w') as fp :
        fp.write(lmp_str)
    os.chdir(cwd)

def water_bond(iter_name, skip = 1) :
    fdump = os.path.join(iter_name, 'dump.equi')
    lines = open(fdump).read().split('\n')
    sections = []
    for ii in range(len(lines)) :
        if 'ITEM: TIMESTEP' in lines[ii] :
            sections.append(ii)
    sections.append(len(lines)-1) 
    all_rr = []
    all_tt = []
    for ii in range(skip, len(sections)-1) :
        sys_data = lib.dump.system_data(lines[sections[ii]:sections[ii+1]])
        atype = sys_data['atom_types']
        posis = sys_data['coordinates']
        cell  = sys_data['cell']
        bonds = compute_bonds(cell, atype, posis)
        if ii == skip : 
            bonds_0 = bonds 
        else :
            if bonds_0 != bonds :
                print('proton trans detected at frame %d' % ii)
        rr = []
        tt = []
        for ii in range(len(bonds)) :
            if atype[ii] == 1 :
                i_idx = ii
                j_idx = bonds[i_idx][0]
                k_idx = bonds[i_idx][1]
                drj = posi_diff(cell, posis[i_idx], posis[j_idx])
                drk = posi_diff(cell, posis[i_idx], posis[k_idx])
                ndrj = np.linalg.norm(drj)
                ndrk = np.linalg.norm(drk)
                rr.append(ndrj)
                rr.append(ndrk)
                tt.append(np.arccos(np.dot(drj,drk) / (ndrj*ndrk)))
        all_rr += rr
        all_tt += tt
    print('# statistics over %d frames %d angles' % (len(sections)-1, len(all_tt)))
    return (np.average(all_rr)), (np.average(all_tt))


def _main ():
    parser = argparse.ArgumentParser(
        description="Equilibrium simulation")
    subparsers = parser.add_subparsers(title='Valid subcommands', dest='command')

    parser_gen = subparsers.add_parser('gen', help='Generate a job')
    parser_gen.add_argument('PARAM', type=str ,
                            help='json parameter file')
    parser_gen.add_argument('-t','--temperature', type=float,
                            help='the temperature of the system')
    parser_gen.add_argument('-p','--pressure', type=float,
                            help='the pressure of the system')
    parser_gen.add_argument('-o','--output', type=str, default = 'new_job',
                            help='the output folder for the job')

    parser_comp = subparsers.add_parser('extract', help= 'Extract the conf')
    parser_comp.add_argument('JOB', type=str ,
                             help='folder of the job')
    parser_comp.add_argument('-o','--output', type=str, default = 'conf.lmp',
                             help='output conf file name')

    parser_stat = subparsers.add_parser('stat-bond', help= 'Statistic of the bonds')
    parser_stat.add_argument('JOB', type=str ,
                             help='folder of the job')
    parser_stat.add_argument('-s','--skip', type=int, default = 1,
                             help='skip this number of frames')
    args = parser.parse_args()

    
    if args.command is None :
        parser.print_help()
        exit
    if args.command == 'gen' :
        jdata = json.load(open(args.PARAM, 'r'))        
        make_task(args.output, jdata, args.temperature, args.pressure)
    elif args.command == 'extract' :
        extract(args.JOB, args.output)
    elif args.command == 'stat-bond' :
        b, a = water_bond(args.JOB, args.skip)
        print(b, a/np.pi*180)

if __name__ == '__main__' :
    _main()