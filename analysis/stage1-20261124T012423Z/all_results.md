# Stage 1 — Complete Results

Run: `stage1-20261124T012423Z`  
Code: `5101804b3db69b5b0e09f872849a8acb1d2313c9`

All 99 method rows are retained below. Optimization time is the median of 10 timed calls in milliseconds; Original is N/A. T-count for QFT is N/A. Positive reduction percentages mean improvement. Categories refer to T + 2Q, except QFT (2Q + depth).

| Circuit ID | Method | T-count | 2Q count | Depth | Time (ms) | Verification |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| qft_4q | Original | N/A | 18 | 24 | N/A | passed |
| qft_4q | Gate-only | N/A | 17 | 19 | 1.737 | passed |
| qft_4q | ZX | N/A | 20 | 25 | 8.002 | passed |
| qft_6q | Original | N/A | 39 | 40 | N/A | passed |
| qft_6q | Gate-only | N/A | 38 | 31 | 4.109 | passed |
| qft_6q | ZX | N/A | 53 | 59 | 29.338 | passed |
| qft_8q | Original | N/A | 68 | 56 | N/A | passed |
| qft_8q | Gate-only | N/A | 67 | 46 | 7.295 | passed |
| qft_8q | ZX | N/A | 118 | 114 | 77.041 | passed |
| tof_ladder_4q | Original | 14 | 12 | 20 | N/A | passed |
| tof_ladder_4q | Gate-only | 14 | 12 | 21 | 0.880 | passed |
| tof_ladder_4q | ZX | 12 | 24 | 35 | 8.829 | passed |
| tof_ladder_6q | Original | 28 | 24 | 38 | N/A | passed |
| tof_ladder_6q | Gate-only | 28 | 24 | 39 | 1.801 | passed |
| tof_ladder_6q | ZX | 22 | 49 | 63 | 22.882 | passed |
| tof_ladder_8q | Original | 42 | 36 | 56 | N/A | passed |
| tof_ladder_8q | Gate-only | 42 | 36 | 57 | 2.608 | passed |
| tof_ladder_8q | ZX | 32 | 59 | 88 | 34.503 | passed |
| phase_4q_s0 | Original | 22 | 48 | 63 | N/A | passed |
| phase_4q_s0 | Gate-only | 8 | 38 | 43 | 2.447 | passed |
| phase_4q_s0 | ZX | 4 | 10 | 13 | 9.609 | passed |
| phase_4q_s1 | Original | 25 | 45 | 59 | N/A | passed |
| phase_4q_s1 | Gate-only | 13 | 45 | 54 | 2.401 | passed |
| phase_4q_s1 | ZX | 5 | 20 | 24 | 11.101 | passed |
| phase_4q_s2 | Original | 20 | 49 | 62 | N/A | passed |
| phase_4q_s2 | Gate-only | 12 | 37 | 50 | 2.247 | passed |
| phase_4q_s2 | ZX | 6 | 18 | 21 | 12.341 | passed |
| phase_6q_s0 | Original | 18 | 56 | 45 | N/A | passed |
| phase_6q_s0 | Gate-only | 10 | 38 | 37 | 2.169 | passed |
| phase_6q_s0 | ZX | 8 | 34 | 34 | 14.327 | passed |
| phase_6q_s1 | Original | 17 | 46 | 41 | N/A | passed |
| phase_6q_s1 | Gate-only | 15 | 40 | 33 | 2.275 | passed |
| phase_6q_s1 | ZX | 13 | 46 | 40 | 22.905 | passed |
| phase_6q_s2 | Original | 23 | 45 | 46 | N/A | passed |
| phase_6q_s2 | Gate-only | 13 | 41 | 37 | 2.350 | passed |
| phase_6q_s2 | ZX | 13 | 43 | 34 | 20.699 | passed |
| phase_8q_s0 | Original | 22 | 48 | 35 | N/A | passed |
| phase_8q_s0 | Gate-only | 10 | 48 | 35 | 2.411 | passed |
| phase_8q_s0 | ZX | 10 | 66 | 46 | 18.648 | passed |
| phase_8q_s1 | Original | 26 | 43 | 33 | N/A | passed |
| phase_8q_s1 | Gate-only | 14 | 43 | 35 | 2.635 | passed |
| phase_8q_s1 | ZX | 14 | 71 | 60 | 27.491 | passed |
| phase_8q_s2 | Original | 20 | 52 | 39 | N/A | passed |
| phase_8q_s2 | Gate-only | 18 | 46 | 35 | 2.555 | passed |
| phase_8q_s2 | ZX | 18 | 76 | 56 | 26.692 | passed |
| pauli_4q_r2 | Original | 6 | 12 | 19 | N/A | passed |
| pauli_4q_r2 | Gate-only | 6 | 10 | 18 | 0.654 | passed |
| pauli_4q_r2 | ZX | 6 | 10 | 17 | 4.137 | passed |
| pauli_4q_r4 | Original | 12 | 24 | 35 | N/A | passed |
| pauli_4q_r4 | Gate-only | 12 | 18 | 34 | 1.295 | passed |
| pauli_4q_r4 | ZX | 12 | 14 | 32 | 7.896 | passed |
| pauli_4q_r8 | Original | 24 | 48 | 67 | N/A | passed |
| pauli_4q_r8 | Gate-only | 24 | 34 | 66 | 2.518 | passed |
| pauli_4q_r8 | ZX | 24 | 20 | 59 | 14.941 | passed |
| pauli_6q_r2 | Original | 10 | 20 | 27 | N/A | passed |
| pauli_6q_r2 | Gate-only | 10 | 18 | 26 | 1.153 | passed |
| pauli_6q_r2 | ZX | 10 | 27 | 35 | 7.527 | passed |
| pauli_6q_r4 | Original | 20 | 40 | 43 | N/A | passed |
| pauli_6q_r4 | Gate-only | 20 | 34 | 42 | 2.210 | passed |
| pauli_6q_r4 | ZX | 20 | 32 | 51 | 14.320 | passed |
| pauli_6q_r8 | Original | 40 | 80 | 75 | N/A | passed |
| pauli_6q_r8 | Gate-only | 40 | 66 | 74 | 4.331 | passed |
| pauli_6q_r8 | ZX | 40 | 59 | 98 | 32.529 | passed |
| pauli_8q_r2 | Original | 14 | 28 | 35 | N/A | passed |
| pauli_8q_r2 | Gate-only | 14 | 26 | 34 | 1.662 | passed |
| pauli_8q_r2 | ZX | 14 | 47 | 47 | 13.461 | passed |
| pauli_8q_r4 | Original | 28 | 56 | 51 | N/A | passed |
| pauli_8q_r4 | Gate-only | 28 | 50 | 50 | 3.088 | passed |
| pauli_8q_r4 | ZX | 28 | 72 | 82 | 20.790 | passed |
| pauli_8q_r8 | Original | 56 | 112 | 83 | N/A | passed |
| pauli_8q_r8 | Gate-only | 56 | 98 | 82 | 6.124 | passed |
| pauli_8q_r8 | ZX | 56 | 108 | 146 | 53.058 | passed |
| clifford_t_4q_s0 | Original | 16 | 44 | 47 | N/A | passed |
| clifford_t_4q_s0 | Gate-only | 10 | 35 | 43 | 3.193 | passed |
| clifford_t_4q_s0 | ZX | 8 | 25 | 33 | 10.970 | passed |
| clifford_t_4q_s1 | Original | 11 | 56 | 56 | N/A | passed |
| clifford_t_4q_s1 | Gate-only | 7 | 41 | 47 | 3.129 | passed |
| clifford_t_4q_s1 | ZX | 5 | 18 | 24 | 10.803 | passed |
| clifford_t_4q_s2 | Original | 20 | 48 | 54 | N/A | passed |
| clifford_t_4q_s2 | Gate-only | 12 | 34 | 46 | 3.252 | passed |
| clifford_t_4q_s2 | ZX | 10 | 27 | 30 | 12.706 | passed |
| clifford_t_6q_s0 | Original | 14 | 45 | 41 | N/A | passed |
| clifford_t_6q_s0 | Gate-only | 10 | 37 | 35 | 3.541 | passed |
| clifford_t_6q_s0 | ZX | 10 | 33 | 29 | 12.190 | passed |
| clifford_t_6q_s1 | Original | 14 | 48 | 39 | N/A | passed |
| clifford_t_6q_s1 | Gate-only | 12 | 41 | 42 | 2.641 | passed |
| clifford_t_6q_s1 | ZX | 12 | 51 | 55 | 14.957 | passed |
| clifford_t_6q_s2 | Original | 19 | 43 | 42 | N/A | passed |
| clifford_t_6q_s2 | Gate-only | 11 | 34 | 40 | 3.511 | passed |
| clifford_t_6q_s2 | ZX | 11 | 49 | 42 | 14.998 | passed |
| clifford_t_8q_s0 | Original | 15 | 41 | 27 | N/A | passed |
| clifford_t_8q_s0 | Gate-only | 9 | 40 | 27 | 2.883 | passed |
| clifford_t_8q_s0 | ZX | 9 | 56 | 40 | 15.428 | passed |
| clifford_t_8q_s1 | Original | 12 | 55 | 34 | N/A | passed |
| clifford_t_8q_s1 | Gate-only | 8 | 48 | 36 | 3.011 | passed |
| clifford_t_8q_s1 | ZX | 8 | 76 | 61 | 21.201 | passed |
| clifford_t_8q_s2 | Original | 19 | 45 | 37 | N/A | passed |
| clifford_t_8q_s2 | Gate-only | 13 | 41 | 40 | 2.473 | passed |
| clifford_t_8q_s2 | ZX | 13 | 62 | 54 | 16.742 | passed |

## Paired comparison against Gate-only

| Circuit ID | T reduction (%) | 2Q reduction (%) | Depth reduction (%) | ZX / Gate time | Category |
| --- | ---: | ---: | ---: | ---: | --- |
| qft_4q | N/A | -17.6 | -31.6 | 4.61 | regression |
| qft_6q | N/A | -39.5 | -90.3 | 7.14 | regression |
| qft_8q | N/A | -76.1 | -147.8 | 10.56 | regression |
| tof_ladder_4q | 14.3 | -100.0 | -66.7 | 10.04 | tradeoff |
| tof_ladder_6q | 21.4 | -104.2 | -61.5 | 12.71 | tradeoff |
| tof_ladder_8q | 23.8 | -63.9 | -54.4 | 13.23 | tradeoff |
| phase_4q_s0 | 50.0 | 73.7 | 69.8 | 3.93 | improvement |
| phase_4q_s1 | 61.5 | 55.6 | 55.6 | 4.62 | improvement |
| phase_4q_s2 | 50.0 | 51.4 | 58.0 | 5.49 | improvement |
| phase_6q_s0 | 20.0 | 10.5 | 8.1 | 6.61 | improvement |
| phase_6q_s1 | 13.3 | -15.0 | -21.2 | 10.07 | tradeoff |
| phase_6q_s2 | 0.0 | -4.9 | 8.1 | 8.81 | regression |
| phase_8q_s0 | 0.0 | -37.5 | -31.4 | 7.73 | regression |
| phase_8q_s1 | 0.0 | -65.1 | -71.4 | 10.43 | regression |
| phase_8q_s2 | 0.0 | -65.2 | -60.0 | 10.45 | regression |
| pauli_4q_r2 | 0.0 | 0.0 | 5.6 | 6.33 | unchanged |
| pauli_4q_r4 | 0.0 | 22.2 | 5.9 | 6.10 | improvement |
| pauli_4q_r8 | 0.0 | 41.2 | 10.6 | 5.93 | improvement |
| pauli_6q_r2 | 0.0 | -50.0 | -34.6 | 6.53 | regression |
| pauli_6q_r4 | 0.0 | 5.9 | -21.4 | 6.48 | improvement |
| pauli_6q_r8 | 0.0 | 10.6 | -32.4 | 7.51 | improvement |
| pauli_8q_r2 | 0.0 | -80.8 | -38.2 | 8.10 | regression |
| pauli_8q_r4 | 0.0 | -44.0 | -64.0 | 6.73 | regression |
| pauli_8q_r8 | 0.0 | -10.2 | -78.0 | 8.66 | regression |
| clifford_t_4q_s0 | 20.0 | 28.6 | 23.3 | 3.44 | improvement |
| clifford_t_4q_s1 | 28.6 | 56.1 | 48.9 | 3.45 | improvement |
| clifford_t_4q_s2 | 16.7 | 20.6 | 34.8 | 3.91 | improvement |
| clifford_t_6q_s0 | 0.0 | 10.8 | 17.1 | 3.44 | improvement |
| clifford_t_6q_s1 | 0.0 | -24.4 | -31.0 | 5.66 | regression |
| clifford_t_6q_s2 | 0.0 | -44.1 | -5.0 | 4.27 | regression |
| clifford_t_8q_s0 | 0.0 | -40.0 | -48.1 | 5.35 | regression |
| clifford_t_8q_s1 | 0.0 | -58.3 | -69.4 | 7.04 | regression |
| clifford_t_8q_s2 | 0.0 | -51.2 | -35.0 | 6.77 | regression |

Data: [paired CSV](paired_results.csv), [family summary](family_summary.csv), [timing components](runtime_components.csv), [raw rows](../../runs/stage1-20261124T012423Z/results.csv).
