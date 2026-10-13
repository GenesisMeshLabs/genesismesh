### Fixed

- **A key named as its own holder is refused at start.** `OPERATOR_KEY_HOLDERS_JSON={"k": "k"}` was
  accepted silently, but a key that is its own holder is unnamed, so every review it took part in was
  refused with `review_needs_named_holder`. The NA now refuses to start and names the keys: name the
  person or team that holds each key, or leave the key out.
- **The default due queue leaves out remediated changes.** `GET /admin/evidence/remediations` without
  `state` listed a remediated change whose review was still pending (for example a review opened
  automatically for a flagged judgement). A remediated change is settled: the default queue now lists
  the due, overdue and waived changes and the other changes with a pending review. `state=review_pending`
  still lists every change with a pending review, remediated ones included.

### Upgrading

- An NA whose `OPERATOR_KEY_HOLDERS_JSON` names a key as its own holder does not start on 1.5.0: remove
  the entry or name the holder.
