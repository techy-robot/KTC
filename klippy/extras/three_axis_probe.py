# Klipper / Kalico extra module for Generalized 3-Axis 1-Break Sensor Probes
# (Compatible with Nudge probes, custom 3D touch sensors, and TypQxQ/KTC ToolChanger)
#
# Copyright (C) 2026 Asher Edwards
# Feature added for KTC (Klipper Tool Changer Code)
# This file may be distributed under the terms of the GNU GPLv3 license.

import logging

class ThreeAxisProbe:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()
        
        # General probe configuration parameters
        self.pin = config.get('pin')
        self.fixed_x = config.getfloat('x', 150.0)
        self.fixed_y = config.getfloat('y', 10.0)
        self.z_hop = config.getfloat('z_hop', 10.0)
        self.z_probe_depth = config.getfloat('z_probe_depth', -2.0)
        self.search_dist = config.getfloat('search_dist', 6.0)
        self.z_expected = config.getfloat('z_expected', 0.0)
        self.tolerance = config.getfloat('tolerance', 0.35)
        self.speed = config.getfloat('speed', 2.0)
        self.debug = config.getboolean('debug', False)
        
        # Optional customizable macro callbacks from config
        self.on_align_gcode = config.get('on_align_gcode', '')
        self.on_blob_detected_gcode = config.get('on_blob_detected_gcode', '')
        
        # Probing state tracking accessible to custom G-code macros
        self.probe_status = "IDLE"
        self.last_tool_name = "none"
        self.last_offset_x = 0.0
        self.last_offset_y = 0.0
        self.last_offset_z = 0.0
        self.last_z_apex = 0.0
        self.last_x_center = 0.0
        self.last_y_center = 0.0
        self.last_probed_z = 0.0
        self.last_blob_detected = False
        self.last_query_triggered = False
        
        # Setup MCU endstop pin for hardware interrupt polling during motion
        ppins = self.printer.lookup_object('pins')
        self.mcu_endstop = ppins.setup_pin('endstop', self.pin)

    def get_status(self, eventtime=None):
        return {
            'name': self.name,
            'pin': self.pin,
            'fixed_x': self.fixed_x,
            'fixed_y': self.fixed_y,
            'z_hop': self.z_hop,
            'z_probe_depth': self.z_probe_depth,
            'search_dist': self.search_dist,
            'z_expected': self.z_expected,
            'tolerance': self.tolerance,
            'speed': self.speed,
            'debug': self.debug,
            'status': self.probe_status,
            'last_tool_name': self.last_tool_name,
            'last_offset_x': self.last_offset_x,
            'last_offset_y': self.last_offset_y,
            'last_offset_z': self.last_offset_z,
            'last_z_apex': self.last_z_apex,
            'last_x_center': self.last_x_center,
            'last_y_center': self.last_y_center,
            'last_probed_z': self.last_probed_z,
            'last_blob_detected': self.last_blob_detected,
            'last_query_triggered': self.last_query_triggered,
        }

    def _probing_move(self, toolhead, target_pos, speed):
        """Execute a probing move stopping on mcu_endstop trigger."""
        homing = self.printer.lookup_object('homing')
        kin = toolhead.get_kinematics()
        steppers = kin.get_steppers()
        
        if self.debug:
            logging.info(f"3-Axis Probe '{self.name}': probing move towards {target_pos} at speed {speed}")
            
        probe_session = homing.probing_move(self.mcu_endstop, steppers, target_pos, speed)
        endpoint = probe_session.get_endpoint()
        
        if self.debug:
            logging.info(f"3-Axis Probe '{self.name}': triggered at endpoint {endpoint}")
            
        return endpoint

    cmd_QUERY_PROBE_help = "Query manual trigger state of the 3-axis 1-break probe switch"
    def cmd_QUERY_PROBE(self, gcmd):
        toolhead = self.printer.lookup_object('toolhead')
        print_time = toolhead.get_last_move_time()
        triggered = self.mcu_endstop.query_endstop(print_time)
        self.last_query_triggered = bool(triggered)
        
        state_str = "TRIGGERED (Contact Detected)" if triggered else "OPEN (No Contact)"
        gcmd.respond_info(f"3-Axis Probe '{self.name}' [{self.pin}] status: {state_str}")

    def _probe_2pass_center(self, toolhead, start_x, start_y, z_height, verbose=False, gcmd=None):
        """
        Iterative 2-Pass Probing on round probe geometry.
        Pass 1 finds approximate center; Pass 2 probes at exact orthogonal apex 
        to eliminate glancing contact error.
        """
        x_center = start_x
        y_center = start_y
        
        for pass_num in range(1, 3):
            if verbose and gcmd:
                gcmd.respond_info(f"--- Probing Pass {pass_num} (Center estimate: X={x_center:.3f}, Y={y_center:.3f}) ---")
                
            # Probe X+ and X- at current y_center estimate
            toolhead.manual_move([x_center + self.search_dist, y_center, z_height], 50.0)
            pos_x1 = self._probing_move(toolhead, [x_center - self.search_dist, y_center, z_height], self.speed)
            
            toolhead.manual_move([x_center - self.search_dist, y_center, z_height], 50.0)
            pos_x2 = self._probing_move(toolhead, [x_center + self.search_dist, y_center, z_height], self.speed)
            
            x_center = (pos_x1[0] + pos_x2[0]) / 2.0
            
            # Probe Y+ and Y- at refined x_center
            toolhead.manual_move([x_center, y_center + self.search_dist, z_height], 50.0)
            pos_y1 = self._probing_move(toolhead, [x_center, y_center - self.search_dist, z_height], self.speed)
            
            toolhead.manual_move([x_center, y_center - self.search_dist, z_height], 50.0)
            pos_y2 = self._probing_move(toolhead, [x_center + self.search_dist, y_center, z_height], self.speed)
            
            y_center = (pos_y1[1] + pos_y2[1]) / 2.0
            
            if verbose and gcmd:
                gcmd.respond_info(f"Pass {pass_num} calculated center: X={x_center:.4f}, Y={y_center:.4f}")
            
        return x_center, y_center

    cmd_ALIGN_TOOL_help = (
        "Align toolhead offsets (X, Y, Z or ALL) using 3-axis probe.\n"
        "Parameters: [AXIS=ALL|X|Y|Z] [TOOL=<name>] [SPEED=<val>] [DISTANCE=<val>] "
        "[DIRECTION=1|-1] [TARGET=<val>] [VERBOSE=0|1] [SAVE=0|1]"
    )
    def cmd_ALIGN_TOOL(self, gcmd):
        axis = gcmd.get('AXIS', 'ALL').upper()
        if axis not in ['ALL', 'X', 'Y', 'Z']:
            raise gcmd.error("Invalid AXIS parameter. Must be ALL, X, Y, or Z.")

        toolhead = self.printer.lookup_object('toolhead')
        speed = gcmd.get_float('SPEED', self.speed)
        dist = gcmd.get_float('DISTANCE', self.search_dist)
        verbose = gcmd.get_int('VERBOSE', 0) == 1 or self.debug

        # Single axis probe mode
        if axis in ['X', 'Y', 'Z']:
            cur_pos = toolhead.get_position()
            direction = gcmd.get_float('DIRECTION', -1.0)
            target_pos = list(cur_pos)
            axis_idx = {'X': 0, 'Y': 1, 'Z': 2}[axis]
            
            params = gcmd.get_command_parameters()
            if 'TARGET' in params:
                target_pos[axis_idx] = float(params['TARGET'])
            else:
                target_pos[axis_idx] = cur_pos[axis_idx] + (direction * dist)
                
            gcmd.respond_info(
                f"3-Axis Probe '{self.name}': Probing {axis}-axis from {cur_pos[axis_idx]:.3f} "
                f"towards {target_pos[axis_idx]:.3f} at speed {speed} mm/s..."
            )
            
            end_pos = self._probing_move(toolhead, target_pos, speed)
            gcmd.respond_info(
                f"3-Axis Probe Triggered! Endpoint: X={end_pos[0]:.4f}, Y={end_pos[1]:.4f}, Z={end_pos[2]:.4f}"
            )
            return

        # Full 3D Tool Alignment mode (AXIS=ALL)
        ktc = self.printer.lookup_object('ktc', None)
        should_save = gcmd.get_int('SAVE', 1) == 1

        # Identify target tool: explicit TOOL parameter, active KTC tool, or GLOBAL
        tool_param = gcmd.get('TOOL', None)
        active_tool_name = None
        ktc_tool_obj = None

        if tool_param and str(tool_param).lower() not in ["global", "none"]:
            active_tool_name = str(tool_param)
            if ktc is not None:
                ktc_tool_obj = ktc.all_tools.get(active_tool_name, None)
        elif not tool_param and ktc is not None:
            if hasattr(ktc, 'active_tool') and ktc.active_tool not in getattr(ktc, 'INVALID_TOOLS', []):
                ktc_tool_obj = ktc.active_tool
                active_tool_name = ktc_tool_obj.name

        # If no tool is specified or active, target is GLOBAL
        if not active_tool_name or active_tool_name in ["tool_none", "", "-1", "UNKNOWN"]:
            active_tool_name = "GLOBAL"

        is_global = (active_tool_name == "GLOBAL")

        cur_pos = toolhead.get_position()
        self.probe_status = "ALIGNING"
        self.last_tool_name = str(active_tool_name)
        
        # 1. Approach probe at safe Z
        toolhead.manual_move([cur_pos[0], cur_pos[1], self.z_hop], 50.0)
        toolhead.manual_move([self.fixed_x, self.fixed_y, self.z_hop], 150.0)
        
        # 2. Probe Z-axis top apex
        pos_z = self._probing_move(toolhead, [self.fixed_x, self.fixed_y, 0.0], speed)
        z_apex = pos_z[2]
        
        # Move back up to safe height
        toolhead.manual_move([self.fixed_x, self.fixed_y, self.z_hop], 50.0)
        
        # 3. Perform 2-pass iterative X/Y probing at z_probe_depth below apex
        xy_probe_z = z_apex + self.z_probe_depth
        x_center, y_center = self._probe_2pass_center(toolhead, self.fixed_x, self.fixed_y, xy_probe_z, verbose, gcmd)
        
        # 4. Calculate relative offsets
        offset_x = round(x_center - self.fixed_x, 4)
        offset_y = round(y_center - self.fixed_y, 4)
        offset_z = round(z_apex - self.z_expected, 4)
        
        self.last_offset_x = offset_x
        self.last_offset_y = offset_y
        self.last_offset_z = offset_z
        self.last_z_apex = z_apex
        self.last_x_center = x_center
        self.last_y_center = y_center
        self.probe_status = "ALIGNED"
        
        # 5. Apply & save offset natively via KTC Python API
        if should_save and ktc is not None:
            new_offset = [offset_x, offset_y, offset_z]
            if is_global or ktc_tool_obj is None:
                ktc.global_offset = new_offset
                ktc.persistent_state_set("global_offset", ktc.global_offset)
                if hasattr(ktc, 'log') and ktc.log:
                    ktc.log.always(f"Global offset set by 3-axis probe to: {ktc.global_offset}")
            else:
                ktc_tool_obj.offset = new_offset
                ktc_tool_obj.persistent_state_set("offset", ktc_tool_obj.offset)
                if hasattr(ktc, 'log') and ktc.log:
                    ktc.log.always(f"Tool '{ktc_tool_obj.name}' offset set by 3-axis probe to: {ktc_tool_obj.offset}")

        target_descr = "GLOBAL offset" if is_global else f"tool '{active_tool_name}'"
        gcmd.respond_info(
            f"3-Axis Probe alignment complete for {target_descr}:\n"
            f"  X_center={x_center:.4f} mm (Offset X={offset_x:.4f} mm)\n"
            f"  Y_center={y_center:.4f} mm (Offset Y={offset_y:.4f} mm)\n"
            f"  Z_apex  ={z_apex:.4f} mm (Offset Z={offset_z:.4f} mm)"
        )

        # 6. Configured custom macro callback execution
        if self.on_align_gcode.strip():
            gcode = self.printer.lookup_object('gcode')
            gcode.run_script_from_command(
                f"{self.on_align_gcode.strip()} TOOL={active_tool_name} X={offset_x:.4f} Y={offset_y:.4f} Z={offset_z:.4f} APEX={z_apex:.4f} X_CENTER={x_center:.4f} Y_CENTER={y_center:.4f}"
            )
        
        toolhead.manual_move([x_center, y_center, self.z_hop], 50.0)

    cmd_CHECK_FILAMENT_help = "Check hotend for stuck filament / blobs using 3-axis probe"
    def cmd_CHECK_FILAMENT(self, gcmd):
        layer = gcmd.get_int('LAYER', 1)
        interval = gcmd.get_int('INTERVAL', 5)
        
        if layer % interval != 0:
            return
            
        toolhead = self.printer.lookup_object('toolhead')
        cur_pos = toolhead.get_position()
        
        safe_z = min(cur_pos[2] + self.z_hop, toolhead.get_status(None)['axis_maximum'][2])
        toolhead.manual_move([cur_pos[0], cur_pos[1], safe_z], 50.0)
        toolhead.manual_move([self.fixed_x, self.fixed_y, safe_z], 150.0)
        
        pos_z = self._probing_move(toolhead, [self.fixed_x, self.fixed_y, 0.0], self.speed)
        probed_z = pos_z[2]
        
        self.last_probed_z = probed_z
        is_blob = probed_z > (self.z_expected + self.tolerance)
        self.last_blob_detected = is_blob
        self.probe_status = "BLOB_DETECTED" if is_blob else "CHECK_PASSED"

        # Configured custom macro callback execution
        if self.on_blob_detected_gcode.strip():
            gcode = self.printer.lookup_object('gcode')
            gcode.run_script_from_command(
                f"{self.on_blob_detected_gcode.strip()} LAYER={layer} PROBED_Z={probed_z:.3f} EXPECTED_Z={self.z_expected:.3f} TOLERANCE={self.tolerance:.3f} BLOB_DETECTED={'1' if is_blob else '0'}"
            )
        
        if is_blob:
            raise gcmd.error(
                f"3-AXIS PROBE SAFETY ALERT: Stuck filament / blob detected on hotend! "
                f"Triggered early at Z={probed_z:.3f}mm (expected max {self.z_expected + self.tolerance:.3f}mm)"
            )
        else:
            gcmd.respond_info(f"3-Axis Probe blob check passed at layer {layer} (Probed Z: {probed_z:.3f}mm)")
            
        toolhead.manual_move([cur_pos[0], cur_pos[1], safe_z], 50.0)
        toolhead.manual_move(cur_pos, 50.0)

def load_config(config):
    return ThreeAxisProbe(config)

# Support [nudge] config section alias
def load_config_prefix(config):
    return ThreeAxisProbe(config)


