# Contribuindo com o AmbGeo LotePro

## Modelo de Branches (GitFlow)

```
main        → produção estável (somente via release/ ou hotfix/)
develop     → integração contínua, base para novas features
feature/*   → novas funcionalidades (saem de develop, voltam para develop)
bugfix/*    → correções não-urgentes (saem de develop, voltam para develop)
release/*   → preparação de versão (saem de develop, voltam para main + develop)
hotfix/*    → correções urgentes em produção (saem de main, voltam para main + develop)
```

## Fluxo de Trabalho

### Nova feature
```bash
git checkout develop
git pull origin develop
git checkout -b feature/nome-da-feature
# ... trabalhe ...
git push -u origin feature/nome-da-feature
# Abra um Pull Request: feature/nome → develop
```

### Correção não-urgente
```bash
git checkout -b bugfix/descricao-do-bug develop
# ... corrija ...
git push -u origin bugfix/descricao-do-bug
# Abra um Pull Request: bugfix/nome → develop
```

### Release
```bash
git checkout -b release/v1.0.0 develop
# Ajuste versão, changelog...
git push -u origin release/v1.0.0
# Pull Request: release/v1.0.0 → main  (e depois merge em develop)
git tag -a v1.0.0 -m "Release v1.0.0"
git push origin v1.0.0
```

### Hotfix (correção urgente em produção)
```bash
git checkout -b hotfix/descricao main
# ... corrija ...
git push -u origin hotfix/descricao
# Pull Request: hotfix/descricao → main  (e depois merge em develop)
```

## Convenção de Commits

Seguimos [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: adiciona cálculo de testada mínima
fix: corrige projeção SIRGAS2000
docs: atualiza README com variáveis de ambiente
refactor: extrai serviço de análise de lotes
test: adiciona testes de validação de geometria
chore: atualiza dependências
```

## Pull Requests

- Todo PR deve apontar para a branch correta (`develop` ou `main`).
- Descreva o que foi feito e como testar.
- PRs para `main` exigem ao menos 1 aprovação.
