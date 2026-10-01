import yaml


class _CfnLoader(yaml.SafeLoader):
    pass


def _any_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


_CfnLoader.add_multi_constructor("!", _any_tag)


def test_sam_template_parses_and_every_env_ref_has_a_parameter():
    """sam build failed once on an unquoted "key: value" in a Description —
    lint/tests never read template.yaml, so parse it here."""
    template = yaml.load(open("template.yaml"), Loader=_CfnLoader)
    params = set(template["Parameters"])
    env = template["Globals"]["Function"]["Environment"]["Variables"]
    refs = {v for v in env.values() if isinstance(v, str) and v in params}
    missing = {k: v for k, v in env.items() if isinstance(v, str) and v[:1].isupper() and v not in params
               and v not in ("CacheTable",)}
    assert refs and not missing


def test_ci_workflow_parses():
    yaml.safe_load(open(".github/workflows/semblance.yml"))
