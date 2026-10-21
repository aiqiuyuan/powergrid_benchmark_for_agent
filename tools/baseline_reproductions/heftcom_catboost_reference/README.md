# CatBoost reference runtime compatibility

This helper is a separate reference runtime for the fixed HEFTCom CatBoost
adaptation. It is not the original competition runtime or a change to historical
agent evaluations. The original data, checker, training and daily replay limits,
one-CPU/eight-GiB contract, and fixed seed remain in force.

Relative to the frozen HEFTCom sandbox, the only added permission is
`LANDLOCK_ACCESS_FS_READ_FILE` for the current process's `/proc/self/statm` object.
CatBoost 1.2.8 uses this memory statistic during fitting. The rule does not grant
directory listing, writing, other `/proc` files, or other processes' memory
statistics. Failure to open or register that exact file stops execution.

The private launcher checks the original source and all input hashes, compiles
this helper in an offline extension of the pinned image, and runs the original
security denials plus targeted `/proc` denials and a synthetic CatBoost fit before
the unchanged 90-day numerical scorer. Failed preparations remain recorded.
