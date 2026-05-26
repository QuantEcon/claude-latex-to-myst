---
title: "Table Long Caption With Math"
---

# Curse of dimensionality

Some intro prose.

````{table}
:name: tab-curse_of_dim

Size of an $n = 10$ Cartesian grid and the 64-bit memory required to store one floating-point value per grid point, as a function of state-space dimension $d$. Grid-based methods are comfortable only at low dimension; by $d = 10$ even storing one scalar per grid point is borderline.

| $d$ | Grid points $(10^d)$ | Memory |
|---|---|---|
| 1 | $10^1$ | 80 B |
| 5 | $10^5$ | 800 kB |
````

See {numref}`tab-curse_of_dim` for the memory profile.
