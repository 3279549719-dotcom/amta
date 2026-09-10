"""amta.stores — 产物/工件存储层。

- artifacts:         产物读写契约（detection/canon/translation/typeset...），schema 单一来源
- artifact_store:    目录型 dir-as-index artifact store
- artifact_cache:    artifact 内容指纹缓存

依赖: amta.common。
"""
