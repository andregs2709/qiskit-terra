# This code is part of Qiskit.
#
# (C) Copyright IBM 2020.
#
# This code is licensed under the Apache License, Version 2.0. You may
# obtain a copy of this license in the LICENSE.txt file in the root directory
# of this source tree or at http://www.apache.org/licenses/LICENSE-2.0.
#
# Any modifications or derivative works of this code must retain this
# copyright notice, and modified files need to carry a notice indicating
# that they have been altered from the originals.

"""ALAP Scheduling."""
from qiskit.circuit import Measure
from qiskit.transpiler.exceptions import TranspilerError

from qiskit.transpiler.passes.scheduling.scheduling.base_scheduler import BaseScheduler


class ALAPScheduleAnalysis(BaseScheduler):
    """ALAP Scheduling pass, which schedules the **stop** time of instructions as late as possible.

    See the :ref:`transpiler-scheduling-description` section in the :mod:`qiskit.transpiler`
    module documentation for a more detailed explanation.
    """

    def run(self, dag):
        """Run the ALAPSchedule pass on `dag`.

        Args:
            dag (DAGCircuit): DAG to schedule.

        Returns:
            DAGCircuit: A scheduled DAG.

        Raises:
            TranspilerError: if the circuit is not mapped on physical qubits.
            TranspilerError: if conditional bit is added to non-supported instruction.
        """
        if len(dag.qregs) != 1 or dag.qregs.get("q", None) is None:
            raise TranspilerError("ALAP schedule runs on physical circuits only")
        if self.property_set["time_unit"] == "stretch":
            raise TranspilerError("Scheduling cannot run on circuits with stretch durations.")

        clbit_write_latency = self.property_set.get("clbit_write_latency", 0)

        node_start_time = {}
        idle_before = {q: 0 for q in dag.qubits + dag.clbits}
        for node in reversed(list(dag.topological_op_nodes())):
            op_duration = self._get_node_duration(node, dag)

            # compute t0, t1: instruction interval, note that
            # t0: start time of instruction
            # t1: end time of instruction

            # since this is alap scheduling, node is scheduled in reversed topological ordering
            # and nodes are packed from the very end of the circuit.
            # the physical meaning of t0 and t1 is flipped here.
            if isinstance(node.op, self.CONDITIONAL_SUPPORTED):
                t0q = max(idle_before[q] for q in node.qargs)
                t0 = t0q
                t1 = t0 + op_duration
            else:
                if isinstance(node.op, Measure):
                    # clbit time is always right (alap) justified
                    t0 = max(idle_before[bit] for bit in node.qargs + node.cargs)
                    t1 = t0 + op_duration
                    #
                    #        |t1 = t0 + duration
                    # Q ░░░░░▒▒▒▒▒▒▒▒▒▒▒
                    # C ░░░░░░░░░▒▒▒▒▒▒▒
                    #            |t0 + (duration - clbit_write_latency)
                    #
                    for clbit in node.cargs:
                        idle_before[clbit] = t0 + (op_duration - clbit_write_latency)
                else:
                    # It happens to be directives such as barrier
                    t0 = max(idle_before[bit] for bit in node.qargs + node.cargs)
                    t1 = t0 + op_duration

            for bit in node.qargs:
                idle_before[bit] = t1

            node_start_time[node] = t1

        # Compute maximum instruction available time, i.e. very end of t1
        circuit_duration = max(idle_before.values())

        # Note that ALAP pass is inversely schedule, thus
        # t0 is computed by subtracting entire circuit duration from t1.
        self.property_set["node_start_time"] = {
            n: circuit_duration - t1 for n, t1 in node_start_time.items()
        }
